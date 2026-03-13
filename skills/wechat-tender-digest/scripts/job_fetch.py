#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

from bid_parser import build_raw_article, extract_text_from_html, safe_filename, save_json
from job_events import emit_progress
from wechat_client import WeChatClient


def fetch_articles(
    client: WeChatClient, config: Any, *, from_date: str, to_date: str, output_dir: Path
) -> Tuple[List[dict], List[dict]]:
    emit_progress("resolve_accounts_started", stage="fetch", job_name=config.job.name, detail="开始解析公众号")
    accounts = client.resolve_accounts(config.source.accounts)
    emit_progress("resolve_accounts_completed", stage="fetch", job_name=config.job.name, current=len(accounts), total=len(config.source.accounts))
    raw_articles: List[dict] = []
    fetch_errors: List[dict] = []
    summary_accounts: List[dict] = []
    for account_index, account in enumerate(accounts, start=1):
        emit_progress("list_articles_started", stage="fetch", job_name=config.job.name, account=account.name, current=account_index, total=len(accounts))
        articles = client.list_articles(account, from_date, to_date)[: int(config.source.limit_per_account)]
        emit_progress(
            "list_articles_completed",
            stage="fetch",
            job_name=config.job.name,
            account=account.name,
            current=len(articles),
            total=int(config.source.limit_per_account),
        )
        items = _download_articles(client, config, output_dir, account.name, articles, raw_articles, fetch_errors)
        summary_accounts.append({"fakeid": account.fakeid, "name": account.name, "articles": items})
    if config.output.keep_raw:
        save_json(
            output_dir / "raw" / "summary.json",
            {"from_date": from_date, "to_date": to_date, "accounts": summary_accounts, "total_articles": len(raw_articles), "fetch_errors": len(fetch_errors)},
        )
    return raw_articles, fetch_errors


def _download_articles(
    client: WeChatClient,
    config: Any,
    output_dir: Path,
    account_name: str,
    articles: List[dict],
    raw_articles: List[dict],
    fetch_errors: List[dict],
) -> List[dict]:
    items: List[dict] = []
    for article_index, article in enumerate(articles, start=1):
        try:
            payload, saved_path = _download_article(client, config, output_dir, account_name, article, article_index, len(articles))
            raw_articles.append(payload)
            items.append({"title": payload["title"], "url": payload["url"], "create_time": payload["create_time"], "saved_path": saved_path})
        except Exception as error:
            fetch_errors.append({"title": str(article.get("title", "unknown")), "account": account_name, "error": str(error)})
    return items


def _download_article(
    client: WeChatClient, config: Any, output_dir: Path, account_name: str, article: dict, article_index: int, article_total: int
) -> Tuple[dict, str]:
    emit_progress(
        "download_article_started",
        stage="fetch",
        job_name=config.job.name,
        account=account_name,
        current=article_index,
        total=article_total,
        detail=str(article.get("title", "")),
    )
    url = str(article.get("url") or article.get("link") or "")
    html_content = client.download_article_html(url)
    payload = build_raw_article(
        article,
        account_name=account_name,
        html_content=html_content,
        text_content=extract_text_from_html(html_content),
    )
    saved_path = _save_raw_article(config, output_dir, account_name, payload)
    emit_progress(
        "download_article_completed",
        stage="fetch",
        job_name=config.job.name,
        account=account_name,
        current=article_index,
        total=article_total,
        detail=payload["title"],
    )
    return payload, saved_path


def _save_raw_article(config: Any, output_dir: Path, account_name: str, payload: dict) -> str:
    if not config.output.keep_raw:
        return ""
    raw_path = output_dir / "raw" / safe_filename(account_name) / f"{safe_filename(payload['title'])}.json"
    save_json(raw_path, payload)
    return str(raw_path)
