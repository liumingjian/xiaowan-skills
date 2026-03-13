#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse


DEFAULT_REQUEST_TTL_SECONDS = 10 * 60


@dataclass(frozen=True)
class MobileRenewalConfig:
    mode: str  # off | spike
    worker_url: str
    host_id: str
    shared_secret: str
    request_ttl_seconds: int


def build_mobile_renewal_config(prefs: Dict[str, str]) -> MobileRenewalConfig:
    mode = _parse_mode(str(prefs.get("mobile_renewal_mode", "")).strip())
    worker_url = str(prefs.get("mobile_renewal_worker_url", "")).strip()
    host_id = str(prefs.get("mobile_renewal_host_id", "")).strip()
    shared_secret = str(prefs.get("mobile_renewal_shared_secret", "")).strip()
    ttl = _parse_non_negative_int(
        str(prefs.get("mobile_renewal_request_ttl_seconds", "")).strip(),
        key="mobile_renewal_request_ttl_seconds",
        default=DEFAULT_REQUEST_TTL_SECONDS,
    )

    if mode == "off":
        return MobileRenewalConfig(
            mode=mode,
            worker_url=worker_url,
            host_id=host_id,
            shared_secret=shared_secret,
            request_ttl_seconds=ttl,
        )

    _require_http_url(worker_url, key="mobile_renewal_worker_url")
    _require_non_empty(host_id, key="mobile_renewal_host_id")
    _require_non_empty(shared_secret, key="mobile_renewal_shared_secret")
    return MobileRenewalConfig(
        mode=mode,
        worker_url=worker_url.rstrip("/"),
        host_id=host_id,
        shared_secret=shared_secret,
        request_ttl_seconds=ttl,
    )


def _parse_mode(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return "off"
    if normalized in ("off", "spike"):
        return normalized
    raise ValueError(f"mobile_renewal_mode 仅支持 off/spike: {value}")


def _parse_non_negative_int(value: str, *, key: str, default: int) -> int:
    if not value:
        return int(default)
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{key} 必须为非负整数: {value}") from error
    if parsed < 0:
        raise ValueError(f"{key} 必须为非负整数: {value}")
    return parsed


def _require_non_empty(value: str, *, key: str) -> None:
    if value:
        return
    raise ValueError(f"缺少配置: {key}")


def _require_http_url(value: str, *, key: str) -> None:
    _require_non_empty(value, key=key)
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{key} 必须是 http(s) URL: {value}")


def is_spike_enabled(config: MobileRenewalConfig) -> bool:
    return config.mode == "spike"


def to_safe_dict(config: MobileRenewalConfig) -> Dict[str, Optional[str]]:
    return {
        "mode": config.mode,
        "worker_url": config.worker_url,
        "host_id": config.host_id,
        "shared_secret": "***" if config.shared_secret else "",
        "request_ttl_seconds": str(config.request_ttl_seconds),
    }

