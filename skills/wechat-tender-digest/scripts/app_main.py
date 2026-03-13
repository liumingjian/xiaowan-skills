#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Optional, Sequence

from app_cli import parse_args
from auth_daemon import DEFAULT_AUTH_CHECK_INTERVAL_SECONDS, DaemonConfig, run_auth_daemon
from auth_manager import AuthManager, AuthManagerError
from deps_check import ensure_dependencies
from doctor import build_doctor_payload
from init_workspace import init_workspace
from job_events import emit_error
from job_creator import handle_create_job
from job_pipeline import run_job
from project_paths import get_auth_qrcode_path, get_auth_state_file
from wechat_auth import AuthStore, LoginError, qr_login_flow
from wechat_client import WeChatClient, WeChatError


def run_cli(argv: Optional[Sequence[str]] = None) -> int:
    all_installed, missing = ensure_dependencies(auto_install=True)
    if not all_installed:
        print(f"✗ 无法自动安装以下依赖: {', '.join(missing)}", file=sys.stderr)
        print(f"请手动运行: pip install {' '.join(missing)}", file=sys.stderr)
        return 1

    init_workspace()
    args = parse_args(argv)

    try:
        return _dispatch(args)
    except WeChatError as error:
        emit_error(error.event, str(error))
    except AuthManagerError as error:
        emit_error(error.event, str(error))
    except LoginError as error:
        emit_error("login_failed", str(error))
    except ValueError as error:
        emit_error("runtime_invalid", str(error))
    except Exception as error:  # pragma: no cover
        emit_error("runtime_failed", str(error))
    return 1


def _dispatch(args: object) -> int:
    if getattr(args, "login", False):
        return _handle_login()
    if getattr(args, "doctor", False):
        payload = build_doctor_payload(getattr(args, "job", None))
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    if getattr(args, "create_job", False):
        job_path = handle_create_job(args)  # type: ignore[arg-type]
        print(json.dumps({"type": "status", "event": "job_created", "job_path": str(job_path)}, ensure_ascii=False))
        return 0
    if getattr(args, "auth_daemon", False):
        return _handle_auth_daemon(args)  # type: ignore[arg-type]
    return run_job(args)


def _handle_login() -> int:
    store = AuthStore()
    state = qr_login_flow()
    store.save(state)
    print(
        json.dumps(
            {
                "type": "status",
                "event": "login_completed",
                "expires_at": state.expires_at,
                "qrcode_path": str(get_auth_qrcode_path()),
                "auth_state_path": str(get_auth_state_file()),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _handle_auth_daemon(args: object) -> int:
    interval = getattr(args, "auth_check_interval_seconds", None)
    seconds = int(interval) if interval else DEFAULT_AUTH_CHECK_INTERVAL_SECONDS
    if seconds <= 0:
        raise ValueError("--auth-check-interval-seconds 必须为正整数")
    store = AuthStore()
    manager = AuthManager(store, login_flow=qr_login_flow, client_factory=WeChatClient)
    return run_auth_daemon(manager=manager, config=DaemonConfig(interval_seconds=seconds))
