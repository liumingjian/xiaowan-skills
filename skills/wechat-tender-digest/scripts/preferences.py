#!/usr/bin/env python3
"""EXTEND.md preference loading (baoyu-comic pattern).

Three-level lookup: project-level > XDG > ~/.wechat-bid-digest/EXTEND.md
Environment variables override EXTEND.md values.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


EXTEND_FILENAME = "EXTEND.md"
APP_DIR_NAME = ".wechat-bid-digest"


def load_preferences() -> dict[str, str]:
    """Load preferences from EXTEND.md with env var overrides."""
    prefs = _load_extend_md()
    # Environment variables take precedence
    env_overrides = {
        "smtp_host": "SMTP_HOST",
        "smtp_port": "SMTP_PORT",
        "smtp_username": "SMTP_USERNAME",
        "smtp_password": "SMTP_PASSWORD",
        "smtp_from": "SMTP_FROM",
        "smtp_ssl": "SMTP_SSL",
        "smtp_starttls": "SMTP_STARTTLS",
        "smtp_use_default_config": "SMTP_USE_DEFAULT_CONFIG",
        "smtp_default_env_path": "SMTP_DEFAULT_ENV_PATH",
        "wechat_work_webhook": "WECHAT_WORK_WEBHOOK",
        "wechat_work_action_url": "WECHAT_WORK_ACTION_URL",
        "wechat_work_mentioned_list": "WECHAT_WORK_MENTIONED_LIST",
        "wechat_work_mentioned_mobile_list": "WECHAT_WORK_MENTIONED_MOBILE_LIST",
        "wechat_work_notify_cooldown_seconds": "WECHAT_WORK_NOTIFY_COOLDOWN_SECONDS",
        "wechat_work_escalate_after_seconds": "WECHAT_WORK_ESCALATE_AFTER_SECONDS",
        "mobile_renewal_mode": "MOBILE_RENEWAL_MODE",
        "mobile_renewal_worker_url": "MOBILE_RENEWAL_WORKER_URL",
        "mobile_renewal_host_id": "MOBILE_RENEWAL_HOST_ID",
        "mobile_renewal_shared_secret": "MOBILE_RENEWAL_SHARED_SECRET",
        "mobile_renewal_request_ttl_seconds": "MOBILE_RENEWAL_REQUEST_TTL_SECONDS",
    }
    for pref_key, env_key in env_overrides.items():
        env_val = os.environ.get(env_key, "").strip()
        if env_val:
            prefs[pref_key] = env_val
    return prefs


def _load_extend_md() -> dict[str, str]:
    """Load and merge EXTEND.md in precedence order.

    Precedence (highest wins): project-level > XDG > user-level.
    This allows keeping secrets in user-level while overriding non-secrets per project.
    """
    merged: dict[str, str] = {}
    for path in reversed(_extend_search_paths()):
        if not path.exists():
            continue
        merged.update(_parse_extend_md(path.read_text(encoding="utf-8")))
    return merged


def _extend_search_paths() -> list[Path]:
    """Return EXTEND.md search paths in priority order."""
    paths: list[Path] = []

    # 1. Project-level: .wechat-bid-digest/EXTEND.md in cwd
    paths.append(Path.cwd() / APP_DIR_NAME / EXTEND_FILENAME)

    # 2. XDG config: $XDG_CONFIG_HOME/wechat-bid-digest/EXTEND.md
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg_config:
        paths.append(Path(xdg_config) / "wechat-bid-digest" / EXTEND_FILENAME)

    # 3. User-level: ~/.wechat-bid-digest/EXTEND.md
    paths.append(Path.home() / APP_DIR_NAME / EXTEND_FILENAME)

    return paths


def _parse_extend_md(text: str) -> dict[str, str]:
    """Parse markdown list-format key-value pairs from EXTEND.md.

    Expected format:
        ## Section
        - key: value
        - another_key: another value
    """
    prefs: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Match "- key: value" pattern
        match = re.match(r"^-\s+(\w+)\s*:\s*(.+)$", stripped)
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            prefs[key] = value
    return prefs


def get_smtp_preferences() -> dict[str, str]:
    """Load only SMTP-related preferences."""
    all_prefs = load_preferences()
    return {k: v for k, v in all_prefs.items() if k.startswith("smtp_")}


def get_default_preferences() -> dict[str, str]:
    """Load non-SMTP default preferences."""
    all_prefs = load_preferences()
    return {k: v for k, v in all_prefs.items() if k.startswith("default_")}


def get_wechat_work_preferences() -> dict[str, str]:
    """Load WeCom (WeChat Work) webhook preferences."""
    all_prefs = load_preferences()
    return {k: v for k, v in all_prefs.items() if k.startswith("wechat_work_")}


def get_mobile_renewal_preferences() -> dict[str, str]:
    all_prefs = load_preferences()
    return {k: v for k, v in all_prefs.items() if k.startswith("mobile_renewal_")}
