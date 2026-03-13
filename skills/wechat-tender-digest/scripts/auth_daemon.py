#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict

from auth_manager import AuthCheckResult, AuthManager, AuthManagerError


DEFAULT_AUTH_CHECK_INTERVAL_SECONDS = 600


@dataclass(frozen=True)
class DaemonConfig:
    interval_seconds: int


def run_auth_daemon(*, manager: AuthManager, config: DaemonConfig) -> int:
    try:
        while True:
            _tick(manager)
            time.sleep(config.interval_seconds)
    except KeyboardInterrupt:
        return 0


def _tick(manager: AuthManager) -> None:
    now = datetime.now().isoformat()
    try:
        result = manager.check_and_refresh()
        _emit_status(_build_status_payload(result, now))
    except AuthManagerError as error:
        _emit_error({"type": "error", "event": error.event, "message": str(error), "timestamp": now})


def _build_status_payload(result: AuthCheckResult, timestamp: str) -> Dict[str, Any]:
    event = "auth_refreshed" if result.refreshed else "auth_healthy"
    expires_at = getattr(result.state, "expires_at", "")
    return {
        "type": "status",
        "event": event,
        "auth": result.health,
        "expires_at": expires_at,
        "timestamp": timestamp,
    }


def _emit_status(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def _emit_error(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    sys.stderr.flush()

