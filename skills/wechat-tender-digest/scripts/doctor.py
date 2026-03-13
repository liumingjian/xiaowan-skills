#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Optional

from friendly_setup import resolve_job_path
from job_config import load_job_config
from project_paths import get_auth_qrcode_path, get_auth_state_file
from smtp_config_state import inspect_smtp_config
from smtp_sender import test_smtp_connection
from wechat_auth import AuthStore


def build_doctor_payload(explicit_job: Optional[str]) -> Dict[str, Any]:
    store = AuthStore()
    smtp_config = inspect_smtp_config()
    smtp_status = test_smtp_connection(env_path=".env")
    result: Dict[str, Any] = {
        "type": "status",
        "event": "doctor_completed",
        "auth": _check_auth_status(store),
        "smtp": {
            "ready": smtp_config["ready"],
            "message": smtp_config["message"],
            "missing_fields": smtp_config["missing_fields"],
            "use_default_config": smtp_config["use_default_config"],
            "default_env_path": smtp_config["default_env_path"],
            "default_env_exists": smtp_config["default_env_exists"],
            "source": smtp_config["source"],
            "resolved": smtp_status.get("resolved", smtp_config["resolved"]),
            "connection": smtp_status,
        },
    }
    job_path = resolve_job_path(explicit_job)
    if not job_path:
        result["job_path"] = None
        result["next_step"] = "如需邮件模式，先确保 auth.ready=true 且 smtp.ready=true，再执行 run_job.py"
        return result
    result["job_path"] = str(job_path)
    result["accounts"] = list(load_job_config(str(job_path)).source.accounts)
    return result


def _check_auth_status(store: AuthStore) -> Dict[str, Any]:
    state = store.load()
    payload = {
        "ready": False,
        "status": "not_logged_in",
        "message": "尚未登录，请运行 --login 扫码",
        "state_file": str(get_auth_state_file()),
        "qrcode_path": str(get_auth_qrcode_path()),
    }
    if not state.token:
        return payload
    payload["login_time"] = state.login_time
    payload["expires_at"] = state.expires_at
    if state.is_valid():
        payload["ready"] = True
        payload["status"] = "valid"
        payload["message"] = "认证有效"
        return payload
    payload["status"] = "expired"
    payload["message"] = "认证已过期，请运行 --login 重新扫码"
    return payload
