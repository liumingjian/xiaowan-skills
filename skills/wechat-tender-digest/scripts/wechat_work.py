#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests


WEBHOOK_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class WeChatWorkConfig:
    webhook_url: str
    action_url: str
    mentioned_list: Tuple[str, ...]
    mentioned_mobile_list: Tuple[str, ...]


@dataclass(frozen=True)
class WeChatWorkSenderConfig:
    webhook_url: str
    mentioned_list: Tuple[str, ...]
    mentioned_mobile_list: Tuple[str, ...]


def parse_csv(value: str) -> Tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def build_wechat_work_config(prefs: Dict[str, str]) -> WeChatWorkConfig:
    webhook_url = str(prefs.get("wechat_work_webhook", "")).strip()
    if not webhook_url:
        raise ValueError("缺少企业微信机器人 Webhook：请配置 wechat_work_webhook")

    action_url = str(prefs.get("wechat_work_action_url", "")).strip()
    if not action_url:
        raise ValueError(
            "缺少提醒处理链接：请配置 wechat_work_action_url（建议先用 "
            "https://developers.openai.com/codex/app/automations 或你的内部续期操作文档链接）"
        )

    mentioned_list = parse_csv(str(prefs.get("wechat_work_mentioned_list", "")))
    mentioned_mobile_list = parse_csv(str(prefs.get("wechat_work_mentioned_mobile_list", "")))
    return WeChatWorkConfig(
        webhook_url=webhook_url,
        action_url=action_url,
        mentioned_list=mentioned_list,
        mentioned_mobile_list=mentioned_mobile_list,
    )


def build_wechat_work_sender_config(prefs: Dict[str, str]) -> WeChatWorkSenderConfig:
    webhook_url = str(prefs.get("wechat_work_webhook", "")).strip()
    if not webhook_url:
        raise ValueError("缺少企业微信机器人 Webhook：请配置 wechat_work_webhook")
    mentioned_list = parse_csv(str(prefs.get("wechat_work_mentioned_list", "")))
    mentioned_mobile_list = parse_csv(str(prefs.get("wechat_work_mentioned_mobile_list", "")))
    return WeChatWorkSenderConfig(
        webhook_url=webhook_url,
        mentioned_list=mentioned_list,
        mentioned_mobile_list=mentioned_mobile_list,
    )


def validate_action_url(action_url: str) -> Dict[str, Any]:
    parsed = urlparse(action_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"ok": False, "reason": "invalid_url"}
    try:
        response = requests.get(action_url, timeout=WEBHOOK_TIMEOUT_SECONDS, allow_redirects=True)
    except requests.RequestException as error:
        return {"ok": False, "reason": "request_failed", "detail": str(error)}
    status_code = int(response.status_code)
    payload = {
        "ok": 200 <= status_code < 400,
        "reason": "ok" if 200 <= status_code < 400 else "http_error",
        "status_code": status_code,
        "final_url": getattr(response, "url", action_url),
    }
    return payload


def _format_duration_cn(seconds: int) -> str:
    if seconds <= 0:
        return "0 分钟"
    minutes = int(seconds) // 60
    hours = minutes // 60
    days = hours // 24
    rem_hours = hours % 24
    rem_minutes = minutes % 60
    if days:
        return f"{days} 天 {rem_hours} 小时"
    if hours:
        return f"{hours} 小时 {rem_minutes} 分钟"
    return f"{rem_minutes} 分钟"


def build_reminder_content(
    *,
    service_name: str,
    auth_status: str,
    timestamp: str,
    action_url: str,
    handle_hint: Optional[str] = None,
    action_url_check: Optional[Dict[str, Any]] = None,
    incident_first_seen: Optional[str] = None,
    incident_age_seconds: Optional[int] = None,
    notify_count: Optional[int] = None,
    escalated: bool = False,
) -> str:
    hint = handle_hint or "打开 Codex 运行 wechat-tender-digest 的 --login 重新扫码"
    lines = [
        f"【{service_name}】微信授权巡检异常",
        f"- 状态: {auth_status}",
        f"- 时间: {timestamp}",
        f"- 处理: {hint}",
        f"- 链接: {action_url}",
    ]
    action_url_line = _format_action_url_check(action_url_check)
    if action_url_line:
        lines.append(action_url_line)
    if incident_first_seen:
        lines.append(f"- 首次发现: {incident_first_seen}")
    if incident_age_seconds is not None:
        lines.append(f"- 已持续: {_format_duration_cn(int(incident_age_seconds))}")
    if notify_count is not None:
        lines.append(f"- 已提醒: {int(notify_count)} 次")
    if escalated:
        lines.append("- 提醒: 已持续较长时间未恢复，请尽快处理")
    return "\n".join(lines)


def _format_action_url_check(action_url_check: Optional[Dict[str, Any]]) -> Optional[str]:
    if not action_url_check:
        return None
    if action_url_check.get("ok"):
        status_code = action_url_check.get("status_code", "?")
        return f"- 链接检查: 可达（HTTP {status_code}）"
    reason = str(action_url_check.get("reason", "unknown"))
    detail = str(action_url_check.get("detail", "")).strip()
    status_code = action_url_check.get("status_code")
    if status_code is not None:
        return f"- 链接检查: 不可达（HTTP {status_code} / {reason}）"
    if detail:
        return f"- 链接检查: 不可达（{reason}: {detail}）"
    return f"- 链接检查: 不可达（{reason}）"


def send_wechat_work_text(
    *,
    webhook_url: str,
    content: str,
    mentioned_list: Tuple[str, ...] = (),
    mentioned_mobile_list: Tuple[str, ...] = (),
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"msgtype": "text", "text": {"content": content}}
    if mentioned_list:
        payload["text"]["mentioned_list"] = list(mentioned_list)
    if mentioned_mobile_list:
        payload["text"]["mentioned_mobile_list"] = list(mentioned_mobile_list)

    response = requests.post(webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    if int(data.get("errcode", -1)) != 0:
        raise ValueError(f"企业微信 Webhook 发送失败: {json.dumps(data, ensure_ascii=False)}")
    return data
