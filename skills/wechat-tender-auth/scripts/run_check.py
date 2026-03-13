#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence


def _add_wechat_bid_digest_scripts_to_path() -> None:
    scripts_dir = (
        Path(__file__).resolve().parents[2] / "wechat-tender-digest" / "scripts"
    )
    sys.path.insert(0, str(scripts_dir))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check WeChat MP auth health and notify via WeCom webhook.")
    parser.add_argument("--service-name", default="微信授权巡检", help="Service name used in outputs and notifications.")
    parser.add_argument("--notify", action="store_true", help="Send WeCom webhook notification when auth is not healthy.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    _add_wechat_bid_digest_scripts_to_path()

    from auth_check import build_auth_check_payload, run_auth_check
    from job_events import emit_error
    from preferences import load_preferences
    from mobile_renewal_config import build_mobile_renewal_config, is_spike_enabled
    from mobile_renewal_worker_client import create_renewal_request
    from wechat_auth import AuthStore
    from wechat_client import WeChatClient
    from wechat_work import (
        build_reminder_content,
        build_wechat_work_config,
        build_wechat_work_sender_config,
        send_wechat_work_text,
        validate_action_url,
    )
    from wechat_work_notify import build_wechat_work_notify_policy, evaluate_wechat_work_notification

    args = parse_args(argv)
    try:
        store = AuthStore()
        result = run_auth_check(service_name=args.service_name, store=store, client_factory=WeChatClient, now=datetime.now)
        payload = build_auth_check_payload(service_name=args.service_name, health=result.health, timestamp=result.timestamp)

        status = str(result.health.get("authStatus", "unknown"))
        if args.notify:
            _handle_notification(
                payload=payload,
                service_name=args.service_name,
                auth_status=status,
                timestamp=result.timestamp,
                now=datetime.now(),
                get_prefs=load_preferences,
                build_policy=build_wechat_work_notify_policy,
                evaluate=evaluate_wechat_work_notification,
                build_config=build_wechat_work_config,
                build_sender_config=build_wechat_work_sender_config,
                validate_url=validate_action_url,
                build_content=build_reminder_content,
                send_text=send_wechat_work_text,
                build_mobile_config=build_mobile_renewal_config,
                is_spike_enabled_fn=is_spike_enabled,
                create_renewal_request_fn=create_renewal_request,
            )
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as error:
        emit_error("auth_check_failed", str(error))
        return 1


def _handle_notification(
    *,
    payload: dict,
    service_name: str,
    auth_status: str,
    timestamp: str,
    now: datetime,
    get_prefs,
    build_policy,
    evaluate,
    build_config,
    build_sender_config=None,
    validate_url,
    build_content,
    send_text,
    build_mobile_config=None,
    is_spike_enabled_fn=None,
    create_renewal_request_fn=None,
) -> None:
    prefs = get_prefs()
    policy = build_policy(prefs)
    decision = evaluate(auth_status=auth_status, now=now, policy=policy)
    payload["wechat_work_notify_decision"] = decision.to_payload()
    if not decision.should_notify:
        payload["wechat_work_notified"] = False
        return

    action_url, config_meta, handle_hint = _resolve_action_url(
        prefs=prefs,
        service_name=service_name,
        auth_status=auth_status,
        build_config=build_config,
        build_sender_config=build_sender_config,
        build_mobile_config=build_mobile_config,
        is_spike_enabled_fn=is_spike_enabled_fn,
        create_renewal_request_fn=create_renewal_request_fn,
    )
    payload["action_url_source"] = config_meta

    sender = _resolve_sender(prefs=prefs, build_config=build_config, build_sender_config=build_sender_config)
    action_url_check = validate_url(action_url)
    payload["action_url_check"] = action_url_check
    content = build_content(
        service_name=service_name,
        auth_status=auth_status,
        timestamp=timestamp,
        action_url=action_url,
        handle_hint=handle_hint,
        action_url_check=action_url_check,
        incident_first_seen=getattr(decision.incident, "first_seen", None),
        incident_age_seconds=decision.incident_age_seconds,
        notify_count=getattr(decision.incident, "notify_count", None),
        escalated=decision.escalated,
    )
    send_text(
        webhook_url=sender.webhook_url,
        content=content,
        mentioned_list=sender.mentioned_list,
        mentioned_mobile_list=sender.mentioned_mobile_list,
    )
    payload["wechat_work_notified"] = True


def _resolve_sender(*, prefs: dict, build_config, build_sender_config):
    if build_sender_config is not None:
        return build_sender_config(prefs)
    return build_config(prefs)


def _resolve_action_url(
    *,
    prefs: dict,
    service_name: str,
    auth_status: str,
    build_config,
    build_sender_config,
    build_mobile_config,
    is_spike_enabled_fn,
    create_renewal_request_fn,
) -> tuple[str, dict, str]:
    mobile_mode = str(prefs.get("mobile_renewal_mode", "")).strip().lower()
    if mobile_mode == "spike":
        if build_mobile_config is None or is_spike_enabled_fn is None or create_renewal_request_fn is None:
            raise ValueError("spike 模式需要传入 build_mobile_config/is_spike_enabled_fn/create_renewal_request_fn")
        if build_sender_config is None:
            raise ValueError("spike 模式需要 build_sender_config（避免依赖静态 wechat_work_action_url）")
        mobile = build_mobile_config(prefs)
        if not is_spike_enabled_fn(mobile):
            raise ValueError("mobile_renewal_mode=spike 但配置未通过校验")
        req = create_renewal_request_fn(
            worker_url=mobile.worker_url,
            host_id=mobile.host_id,
            shared_secret=mobile.shared_secret,
            service_name=service_name,
            auth_status=auth_status,
            request_ttl_seconds=mobile.request_ttl_seconds,
        )
        return (
            req.action_url,
            {"mode": "spike", "worker_url": mobile.worker_url, "request_id": req.request_id, "expires_at": req.expires_at},
            "手机打开链接后按页面提示在微信中确认登录（无需回到电脑手动点 --login）",
        )
    config = build_config(prefs)
    return (
        config.action_url,
        {"mode": "static", "action_url": config.action_url},
        "",
    )


if __name__ == "__main__":
    raise SystemExit(main())
