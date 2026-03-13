#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

from job_events import emit_error
from mobile_renewal_config import build_mobile_renewal_config, is_spike_enabled, to_safe_dict
from mobile_renewal_worker_client import HostPolledRequest, poll_host, report_result, upload_mobile_payload
from preferences import load_preferences
from wechat_auth import AuthStore, LoginError
from wechat_mp_qr_login import WeChatLoginTimeout, begin_qr_login, build_auth_state, wait_for_login_token


DEFAULT_POLL_INTERVAL_SECONDS = 5


@dataclass(frozen=True)
class AgentOptions:
    once: bool
    poll_interval_seconds: int
    confirm_timeout_seconds: int


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mobile renewal resident agent (spike).")
    parser.add_argument("--once", action="store_true", help="Process at most one poll tick then exit.")
    parser.add_argument("--poll-interval-seconds", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--confirm-timeout-seconds", type=int, default=0, help="0 means use request TTL.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        prefs = load_preferences()
        config = build_mobile_renewal_config(prefs)
        if not is_spike_enabled(config):
            raise ValueError("mobile_renewal_mode=off，未开启 spike；请先配置 mobile_renewal_mode=spike")

        options = AgentOptions(
            once=bool(args.once),
            poll_interval_seconds=_require_positive_int(args.poll_interval_seconds, key="poll_interval_seconds"),
            confirm_timeout_seconds=int(args.confirm_timeout_seconds or 0),
        )
        run_agent(options=options, config=config, store=AuthStore())
        return 0
    except Exception as error:
        emit_error("mobile_renewal_agent_failed", str(error))
        return 1


def run_agent(*, options: AgentOptions, config, store: AuthStore) -> None:
    _emit_status("agent_started", {"config": to_safe_dict(config), "options": asdict(options)})
    while True:
        payload = run_once(options=options, config=config, store=store)
        _emit_status("tick", payload)
        if options.once:
            return
        time.sleep(float(options.poll_interval_seconds))


def run_once(*, options: AgentOptions, config, store: AuthStore) -> Dict[str, Any]:
    request = poll_host(worker_url=config.worker_url, host_id=config.host_id, shared_secret=config.shared_secret)
    if not request:
        return {"event": "no_request"}
    return _process_request(options=options, config=config, store=store, request=request)


def _process_request(*, options: AgentOptions, config, store: AuthStore, request: HostPolledRequest) -> Dict[str, Any]:
    timeout_seconds = int(options.confirm_timeout_seconds or config.request_ttl_seconds)
    try:
        prepared = begin_qr_login()
        qr_b64 = base64.b64encode(prepared.qr_png_bytes).decode("ascii")
        upload_mobile_payload(
            worker_url=config.worker_url,
            request_id=request.request_id,
            shared_secret=config.shared_secret,
            mobile_payload={"kind": "qr_png_base64", "data": qr_b64},
        )
        token = wait_for_login_token(prepared.session, timeout_seconds=timeout_seconds)
        state = build_auth_state(session=prepared.session, token=token)
        store.save(state)
        report_result(
            worker_url=config.worker_url,
            request_id=request.request_id,
            shared_secret=config.shared_secret,
            result={"status": "confirmed", "detail": "token refreshed"},
        )
        return {"event": "renewal_confirmed", "request_id": request.request_id}
    except WeChatLoginTimeout as error:
        report_result(
            worker_url=config.worker_url,
            request_id=request.request_id,
            shared_secret=config.shared_secret,
            result={"status": "expired", "detail": str(error)},
        )
        return {"event": "renewal_expired", "request_id": request.request_id, "error": str(error)}
    except LoginError as error:
        report_result(
            worker_url=config.worker_url,
            request_id=request.request_id,
            shared_secret=config.shared_secret,
            result={"status": "failed", "detail": str(error)},
        )
        return {"event": "renewal_failed", "request_id": request.request_id, "error": str(error)}


def _require_positive_int(value: int, *, key: str) -> int:
    if int(value) <= 0:
        raise ValueError(f"{key} 必须为正整数: {value}")
    return int(value)


def _emit_status(event: str, payload: Dict[str, Any]) -> None:
    output = {"type": "status", "event": event, "timestamp": datetime.now().isoformat(), **payload}
    print(json.dumps(output, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())

