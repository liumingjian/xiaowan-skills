#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from auth_manager import AuthManager
from bid_parser import build_raw_article, collect_records, extract_text_from_html, records_to_json, safe_filename, save_json
from config_resolver import resolve_config
from html_report import build_html
from job_events import attach_fetch_errors, build_stage_payload, finish_with_status, persist_send_result
from output_paths import build_job_date_output_dir
from smtp_sender import SmtpError, send_html_email
from wechat_auth import AuthStore, qr_login_flow
from wechat_client import WeChatClient, WeChatError


@dataclass(frozen=True)
class JobContext:
    config: Any
    from_date: str
    to_date: str
    output_dir: Path
    job_path: str
    auth_info: Dict[str, Any]


@dataclass(frozen=True)
class FetchResult:
    raw_articles: List[dict]
    fetch_errors: List[dict]


def run_job(args: Any) -> int:
    ctx, client = _prepare_context(args)
    return _run_stages(ctx=ctx, client=client, until=args.until)


def _prepare_context(args: Any) -> Tuple[JobContext, WeChatClient]:
    config = resolve_config(args)
    from_date, to_date = resolve_dates(config, args.from_date, args.to_date)
    output_dir = build_job_date_output_dir(root_dir=config.output.root_dir, job_name=config.job.name, to_date=to_date)
    output_dir.mkdir(parents=True, exist_ok=True)

    job_path = getattr(args, "job", None) or "(preset)"

    store = AuthStore()
    manager = AuthManager(store, login_flow=qr_login_flow, client_factory=WeChatClient)
    check = manager.check_and_refresh()
    ensure_healthy(check.health)

    auth_info = {"status": check.health.get("authStatus", "unknown"), "expires_at": getattr(check.state, "expires_at", "")}
    return (
        JobContext(
            config=config,
            from_date=from_date,
            to_date=to_date,
            output_dir=output_dir,
            job_path=job_path,
            auth_info=auth_info,
        ),
        WeChatClient(check.state),
    )


def _run_stages(ctx: JobContext, client: WeChatClient, *, until: str) -> int:
    raw_articles, fetch_errors = fetch_articles(
        client, ctx.config, from_date=ctx.from_date, to_date=ctx.to_date, output_dir=ctx.output_dir
    )
    fetch = FetchResult(raw_articles=raw_articles, fetch_errors=fetch_errors)
    maybe_exit = _finish_if_until(
        ctx, fetch, until=until, stage="fetch", event="fetch_completed", record_count=0, report_path=None
    )
    if maybe_exit is not None:
        return maybe_exit

    records = collect_records(
        fetch.raw_articles, ctx.config.filters.keywords, ctx.config.filters.categories, sort_by=ctx.config.filters.sort_by
    )
    save_parsed_payload(ctx.config, ctx.output_dir, from_date=ctx.from_date, to_date=ctx.to_date, records=records)
    maybe_exit = _finish_if_until(
        ctx, fetch, until=until, stage="parse", event="parse_completed", record_count=len(records), report_path=None
    )
    if maybe_exit is not None:
        return maybe_exit

    report_path, html_body = render_report(ctx.config, ctx.output_dir, from_date=ctx.from_date, to_date=ctx.to_date, records=records)
    event = "no_matching_records" if not records else "render_completed"
    maybe_exit = _finish_if_until(
        ctx, fetch, until=until, stage="render", event=event, record_count=len(records), report_path=report_path
    )
    if maybe_exit is not None:
        return maybe_exit

    send_payload = handle_send(
        ctx.config,
        ctx.output_dir,
        raw_articles=fetch.raw_articles,
        records=records,
        report_path=report_path,
        html_body=html_body,
        from_date=ctx.from_date,
        to_date=ctx.to_date,
        job_path=ctx.job_path,
        auth_info=ctx.auth_info,
    )
    print(json.dumps(attach_fetch_errors(send_payload, fetch.fetch_errors), ensure_ascii=False))
    return 0


def _finish_if_until(
    ctx: JobContext,
    fetch: FetchResult,
    *,
    until: str,
    stage: str,
    event: str,
    record_count: int,
    report_path: Optional[str],
) -> Optional[int]:
    if until != stage:
        return None
    payload = build_stage_payload(
        event,
        ctx.config,
        from_date=ctx.from_date,
        to_date=ctx.to_date,
        raw_articles=fetch.raw_articles,
        record_count=record_count,
        report_path=report_path,
        email_sent=False,
        job_path=ctx.job_path,
        auth_info=ctx.auth_info,
    )
    return finish_with_status(ctx.output_dir, attach_fetch_errors(payload, fetch.fetch_errors))


def resolve_dates(config: Any, from_override: Optional[str], to_override: Optional[str]) -> Tuple[str, str]:
    if bool(from_override) != bool(to_override):
        raise ValueError("--from-date and --to-date must be provided together")
    if from_override and to_override:
        _validate_iso_date(from_override)
        _validate_iso_date(to_override)
        return from_override, to_override
    end_date = date.today()
    start_date = end_date - timedelta(days=int(config.job.window_days) - 1)
    return start_date.isoformat(), end_date.isoformat()


def ensure_healthy(health: Dict[str, Any]) -> None:
    status = str(health.get("authStatus", "unknown"))
    if status == "healthy":
        return
    if status == "expired":
        raise WeChatError("auth_expired", "登录已过期，请运行 --login 重新扫码")
    if status == "unreachable":
        raise WeChatError("auth_unhealthy", "无法连接到微信接口，请检查网络")
    raise WeChatError("auth_unknown", f"认证状态未知: {health}")


def fetch_articles(
    client: WeChatClient, config: Any, *, from_date: str, to_date: str, output_dir: Path
) -> Tuple[List[dict], List[dict]]:
    accounts = client.resolve_accounts(config.source.accounts)
    raw_articles: List[dict] = []
    fetch_errors: List[dict] = []
    summary_accounts: List[dict] = []
    for account in accounts:
        articles = client.list_articles(account, from_date, to_date)[: int(config.source.limit_per_account)]
        items: List[dict] = []
        for article in articles:
            saved_path = ""
            try:
                url = str(article.get("url") or article.get("link") or "")
                html_content = client.download_article_html(url)
                payload = build_raw_article(
                    article,
                    account_name=account.name,
                    html_content=html_content,
                    text_content=extract_text_from_html(html_content),
                )
                raw_articles.append(payload)
                if config.output.keep_raw:
                    raw_path = output_dir / "raw" / safe_filename(account.name) / f"{safe_filename(payload['title'])}.json"
                    save_json(raw_path, payload)
                    saved_path = str(raw_path)
                items.append({"title": payload["title"], "url": payload["url"], "create_time": payload["create_time"], "saved_path": saved_path})
            except Exception as error:
                title = str(article.get("title", "unknown"))
                fetch_errors.append({"title": title, "account": account.name, "error": str(error)})
        summary_accounts.append({"fakeid": account.fakeid, "name": account.name, "articles": items})

    if config.output.keep_raw:
        save_json(
            output_dir / "raw" / "summary.json",
            {
                "from_date": from_date,
                "to_date": to_date,
                "accounts": summary_accounts,
                "total_articles": len(raw_articles),
                "fetch_errors": len(fetch_errors),
            },
        )
    return raw_articles, fetch_errors


def save_parsed_payload(config: Any, output_dir: Path, *, from_date: str, to_date: str, records: list) -> None:
    if not config.output.keep_parsed:
        return
    save_json(
        output_dir / "parsed" / "records.json",
        records_to_json(records, config.job.name, from_date=from_date, to_date=to_date),
    )


def render_report(config: Any, output_dir: Path, *, from_date: str, to_date: str, records: list) -> Tuple[Optional[str], str]:
    html_body = build_html(
        config.job.description,
        records,
        from_date=from_date,
        to_date=to_date,
        keywords=config.filters.keywords,
        layout=config.email.layout,
        visible_fields=config.email.visible_fields,
    )
    if not config.output.keep_report:
        return None, html_body
    path = output_dir / str(config.output.report_filename)
    path.write_text(html_body, encoding="utf-8")
    return str(path), html_body


def handle_send(
    config: Any,
    output_dir: Path,
    *,
    raw_articles: List[dict],
    records: list,
    report_path: Optional[str],
    html_body: str,
    from_date: str,
    to_date: str,
    job_path: str,
    auth_info: Dict[str, Any],
) -> Dict[str, Any]:
    base = {
        "from_date": from_date,
        "to_date": to_date,
        "raw_articles": raw_articles,
        "report_path": report_path,
        "job_path": job_path,
        "auth_info": auth_info,
    }
    record_count = len(records)
    if not config.email.enabled:
        payload = build_stage_payload("send_skipped", config, record_count=record_count, email_sent=False, **base)
        payload["reason"] = "email_disabled"
        return persist_send_result(output_dir, payload)
    if not records and not config.email.send_on_empty:
        payload = build_stage_payload("no_matching_records", config, record_count=0, email_sent=False, **base)
        payload["reason"] = "send_on_empty_disabled"
        return persist_send_result(output_dir, payload)
    try:
        send_payload = send_html_email(html_body, config.email.to, config.email.subject, env_path=".env")
    except SmtpError as error:
        payload = build_stage_payload("smtp_failed", config, record_count=record_count, email_sent=False, **base)
        payload["error"] = str(error)
        payload["reason"] = "smtp_send_failed"
        return persist_send_result(output_dir, payload)
    payload = build_stage_payload("email_sent", config, record_count=record_count, email_sent=True, **base)
    payload["message_id"] = send_payload["message_id"]
    return persist_send_result(output_dir, payload)


def _validate_iso_date(value: str) -> None:
    datetime.strptime(value, "%Y-%m-%d")
