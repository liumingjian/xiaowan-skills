#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from project_paths import get_wecom_state_file

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE

DEFAULT_NOTIFY_COOLDOWN_SECONDS = 6 * SECONDS_PER_HOUR
DEFAULT_ESCALATE_AFTER_SECONDS = 24 * SECONDS_PER_HOUR

@dataclass(frozen=True)
class WeChatWorkNotifyPolicy:
    cooldown_seconds: int
    escalate_after_seconds: int
    state_file: Path


@dataclass(frozen=True)
class IncidentState:
    auth_status: str
    first_seen: str
    last_seen: str
    last_notified: str
    notify_count: int


@dataclass(frozen=True)
class NotifyDecision:
    should_notify: bool
    reason: str
    incident: Optional[IncidentState]
    escalated: bool
    incident_age_seconds: int

    def to_payload(self) -> Dict[str, Any]:
        return {
            "should_notify": self.should_notify,
            "reason": self.reason,
            "escalated": self.escalated,
            "incident_age_seconds": self.incident_age_seconds,
            "incident": asdict(self.incident) if self.incident else None,
        }


def build_wechat_work_notify_policy(
    prefs: Dict[str, str],
    *,
    state_file: Optional[Path] = None,
) -> WeChatWorkNotifyPolicy:
    cooldown = _parse_non_negative_int(
        str(prefs.get("wechat_work_notify_cooldown_seconds", "")).strip(),
        key="wechat_work_notify_cooldown_seconds",
        default=DEFAULT_NOTIFY_COOLDOWN_SECONDS,
    )
    escalate_after = _parse_non_negative_int(
        str(prefs.get("wechat_work_escalate_after_seconds", "")).strip(),
        key="wechat_work_escalate_after_seconds",
        default=DEFAULT_ESCALATE_AFTER_SECONDS,
    )
    return WeChatWorkNotifyPolicy(
        cooldown_seconds=cooldown,
        escalate_after_seconds=escalate_after,
        state_file=state_file or get_wecom_state_file(),
    )


def evaluate_wechat_work_notification(
    *,
    auth_status: str,
    now: datetime,
    policy: WeChatWorkNotifyPolicy,
) -> NotifyDecision:
    if auth_status == "healthy":
        _clear_incident(policy.state_file)
        return NotifyDecision(
            should_notify=False,
            reason="healthy",
            incident=None,
            escalated=False,
            incident_age_seconds=0,
        )

    current = _load_incident(policy.state_file)
    updated = _upsert_incident(current, auth_status=auth_status, now=now)
    age_seconds = _age_seconds(updated, now=now)
    escalated = bool(policy.escalate_after_seconds) and age_seconds >= policy.escalate_after_seconds

    should_notify, reason = _should_notify(updated, now=now, cooldown_seconds=policy.cooldown_seconds)
    final_incident = updated
    if should_notify:
        final_incident = _mark_notified(updated, now=now)
    _save_incident(policy.state_file, final_incident)

    return NotifyDecision(
        should_notify=should_notify,
        reason=reason,
        incident=final_incident,
        escalated=escalated,
        incident_age_seconds=age_seconds,
    )


def _parse_non_negative_int(value: str, *, key: str, default: int) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{key} 必须为非负整数: {value}") from error
    if parsed < 0:
        raise ValueError(f"{key} 必须为非负整数: {value}")
    return parsed


def _load_incident(path: Path) -> Optional[IncidentState]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"通知状态文件损坏，无法解析 JSON: {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"通知状态文件格式错误（应为 object）: {path}")
    try:
        return IncidentState(
            auth_status=str(data["auth_status"]),
            first_seen=str(data["first_seen"]),
            last_seen=str(data["last_seen"]),
            last_notified=str(data.get("last_notified", "")),
            notify_count=int(data.get("notify_count", 0)),
        )
    except KeyError as error:
        raise ValueError(f"通知状态文件缺少必要字段: {path}") from error


def _save_incident(path: Path, incident: IncidentState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(incident), ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _clear_incident(path: Path) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as error:
        raise ValueError(f"无法清理通知状态文件: {path}") from error


def _upsert_incident(current: Optional[IncidentState], *, auth_status: str, now: datetime) -> IncidentState:
    timestamp = now.isoformat()
    if not current or current.auth_status != auth_status:
        return IncidentState(
            auth_status=auth_status,
            first_seen=timestamp,
            last_seen=timestamp,
            last_notified="",
            notify_count=0,
        )
    return replace(current, last_seen=timestamp)


def _mark_notified(incident: IncidentState, *, now: datetime) -> IncidentState:
    timestamp = now.isoformat()
    return replace(
        incident,
        last_notified=timestamp,
        notify_count=int(incident.notify_count) + 1,
    )


def _should_notify(incident: IncidentState, *, now: datetime, cooldown_seconds: int) -> tuple[bool, str]:
    if not incident.last_notified:
        return True, "first_seen"
    if cooldown_seconds <= 0:
        return True, "cooldown_disabled"

    last = _parse_iso(incident.last_notified, field="last_notified")
    elapsed = (now - last).total_seconds()
    if elapsed >= cooldown_seconds:
        return True, "cooldown_elapsed"
    return False, "cooldown_active"


def _age_seconds(incident: IncidentState, *, now: datetime) -> int:
    first = _parse_iso(incident.first_seen, field="first_seen")
    return int((now - first).total_seconds())


def _parse_iso(value: str, *, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"通知状态时间格式错误（{field}）: {value}") from error
