#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests


DEFAULT_HTTP_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class RenewalRequest:
    request_id: str
    action_url: str
    expires_at: str


@dataclass(frozen=True)
class HostPolledRequest:
    request_id: str
    token: str
    host_id: str
    expires_at: str
    status: str


def create_renewal_request(
    *,
    worker_url: str,
    host_id: str,
    shared_secret: str,
    service_name: str,
    auth_status: str,
    request_ttl_seconds: int,
    timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    now: Optional[datetime] = None,
) -> RenewalRequest:
    base = str(worker_url).rstrip("/")
    url = f"{base}/api/renewals"
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    payload: Dict[str, Any] = {
        "host_id": host_id,
        "service_name": service_name,
        "auth_status": auth_status,
        "requested_at": timestamp,
        "ttl_seconds": int(request_ttl_seconds),
    }
    headers = {
        "Authorization": f"Bearer {shared_secret}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not bool(data.get("ok")):
        raise ValueError(f"Worker 返回异常: {json.dumps(data, ensure_ascii=False)}")

    request_id = str(data.get("request_id", "")).strip()
    action_url = str(data.get("action_url", "")).strip()
    expires_at = str(data.get("expires_at", "")).strip()
    if not request_id or not action_url or not expires_at:
        raise ValueError(f"Worker 返回缺少字段: {json.dumps(data, ensure_ascii=False)}")

    return RenewalRequest(request_id=request_id, action_url=action_url, expires_at=expires_at)


def poll_host(
    *,
    worker_url: str,
    host_id: str,
    shared_secret: str,
    timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> Optional[HostPolledRequest]:
    base = str(worker_url).rstrip("/")
    url = f"{base}/api/hosts/{host_id}/poll"
    headers = {"Authorization": f"Bearer {shared_secret}"}
    response = requests.post(url, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not bool(data.get("ok")):
        raise ValueError(f"Worker 返回异常: {json.dumps(data, ensure_ascii=False)}")
    req = data.get("request")
    if req is None:
        return None
    if not isinstance(req, dict):
        raise ValueError(f"Worker 返回 request 格式错误: {json.dumps(data, ensure_ascii=False)}")
    return HostPolledRequest(
        request_id=str(req.get("request_id", "")).strip(),
        token=str(req.get("token", "")).strip(),
        host_id=str(req.get("host_id", "")).strip(),
        expires_at=str(req.get("expires_at", "")).strip(),
        status=str(req.get("status", "")).strip(),
    )


def upload_mobile_payload(
    *,
    worker_url: str,
    request_id: str,
    shared_secret: str,
    mobile_payload: Dict[str, Any],
    timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> None:
    base = str(worker_url).rstrip("/")
    url = f"{base}/api/renewals/{request_id}/mobile-ready"
    headers = {"Authorization": f"Bearer {shared_secret}"}
    response = requests.post(
        url,
        json={"mobile_payload": mobile_payload},
        headers=headers,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not bool(data.get("ok")):
        raise ValueError(f"Worker 返回异常: {json.dumps(data, ensure_ascii=False)}")


def report_result(
    *,
    worker_url: str,
    request_id: str,
    shared_secret: str,
    result: Dict[str, Any],
    timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> None:
    base = str(worker_url).rstrip("/")
    url = f"{base}/api/renewals/{request_id}/result"
    headers = {"Authorization": f"Bearer {shared_secret}"}
    response = requests.post(
        url,
        json={"result": result},
        headers=headers,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not bool(data.get("ok")):
        raise ValueError(f"Worker 返回异常: {json.dumps(data, ensure_ascii=False)}")
