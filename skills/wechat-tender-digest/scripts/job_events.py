#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from smtp_sender import write_send_result


def persist_send_result(output_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    write_send_result(output_dir / "send-result.json", payload)
    return payload


def emit_status(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def finish_with_status(output_dir: Path, payload: Dict[str, Any]) -> int:
    write_send_result(output_dir / "send-result.json", payload)
    emit_status(payload)
    return 0


def build_stage_payload(
    event: str,
    config: Any,
    *,
    from_date: str,
    to_date: str,
    raw_articles: List[dict],
    record_count: int,
    report_path: Optional[str],
    email_sent: bool,
    job_path: str,
    auth_info: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": "status",
        "event": event,
        "job_name": config.job.name,
        "job_path": job_path,
        "date_range": {"from": from_date, "to": to_date},
        "article_count": len(raw_articles),
        "record_count": record_count,
        "output_path": report_path,
        "email_sent": email_sent,
        "auth": auth_info,
    }


def emit_progress(
    event: str,
    *,
    stage: str,
    job_name: str,
    account: Optional[str] = None,
    current: Optional[int] = None,
    total: Optional[int] = None,
    detail: str = "",
) -> None:
    payload: Dict[str, Any] = {"type": "status", "event": event, "stage": stage, "job_name": job_name}
    if account:
        payload["account"] = account
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    if detail:
        payload["detail"] = detail
    emit_status(payload)


def attach_fetch_errors(payload: Dict[str, Any], fetch_errors: List[dict]) -> Dict[str, Any]:
    if fetch_errors:
        payload["fetch_errors"] = fetch_errors
    return payload


def emit_error(event: str, message: str) -> None:
    print(json.dumps({"type": "error", "event": event, "message": message}, ensure_ascii=False), file=sys.stderr)
    sys.stderr.flush()
