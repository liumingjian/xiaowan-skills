#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Optional

from friendly_setup import resolve_job_path
from job_config import load_job_config
from smtp_sender import test_smtp_connection
from wechat_auth import AuthStore


def build_doctor_payload(explicit_job: Optional[str]) -> Dict[str, Any]:
    store = AuthStore()
    auth_status = _check_auth_status(store)
    smtp_status = test_smtp_connection(env_path=".env")
    result: Dict[str, Any] = {
        "type": "status",
        "event": "doctor_completed",
        "auth": auth_status,
        "smtp": smtp_status,
    }
    job_path = resolve_job_path(explicit_job)
    if job_path:
        result["job_path"] = str(job_path)
        config = load_job_config(str(job_path))
        result["accounts"] = list(config.source.accounts)
    else:
        result["job_path"] = None
        result["next_step"] = "运行 --login 扫码登录，或通过 --job 指定任务配置文件"
    return result


def _check_auth_status(store: AuthStore) -> Dict[str, Any]:
    state = store.load()
    if not state.token:
        return {"status": "not_logged_in", "message": "尚未登录，请运行 --login 扫码"}
    if state.is_valid():
        return {
            "status": "valid",
            "login_time": state.login_time,
            "expires_at": state.expires_at,
            "message": "认证有效",
        }
    return {
        "status": "expired",
        "login_time": state.login_time,
        "expires_at": state.expires_at,
        "message": "认证已过期，请运行 --login 重新扫码",
    }
