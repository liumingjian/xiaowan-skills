#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from auth_manager import AuthManager
from bid_parser import collect_records, records_to_json, save_json
from config_resolver import resolve_config
from html_report import build_html
from job_fetch import fetch_articles
from job_events import attach_fetch_errors, build_stage_payload, emit_progress, finish_with_status, persist_send_result
from output_paths import build_job_date_output_dir
from smtp_config_state import inspect_smtp_config
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
    ensure_email_preflight(config)
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

    emit_progress("parse_started", stage="parse", job_name=ctx.config.job.name, detail="开始提取招投标记录")
    records = collect_records(
        fetch.raw_articles, ctx.config.filters.keywords, ctx.config.filters.categories, sort_by=ctx.config.filters.sort_by
    )
    emit_progress("parse_completed", stage="parse", job_name=ctx.config.job.name, current=len(records), total=len(fetch.raw_articles))
    save_parsed_payload(ctx.config, ctx.output_dir, from_date=ctx.from_date, to_date=ctx.to_date, records=records)
    maybe_exit = _finish_if_until(
        ctx, fetch, until=until, stage="parse", event="parse_completed", record_count=len(records), report_path=None
    )
    if maybe_exit is not None:
        return maybe_exit

    emit_progress("render_started", stage="render", job_name=ctx.config.job.name, current=len(records), detail="开始生成 HTML 报告")
    report_path, html_body = render_report(ctx.config, ctx.output_dir, from_date=ctx.from_date, to_date=ctx.to_date, records=records)
    emit_progress("render_completed", stage="render", job_name=ctx.config.job.name, current=len(records), detail=str(report_path or "report_disabled"))
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


def ensure_email_preflight(config: Any) -> None:
    if not config.email.enabled:
        return
    smtp_status = inspect_smtp_config()
    if smtp_status["ready"]:
        return
    raise ValueError(f"邮件模式必须先运行 --doctor 并补齐 SMTP 配置。\n{smtp_status['message']}")
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
