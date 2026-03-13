#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from project_paths import get_default_smtp_env_path


TRUE_VALUES = {"1", "true", "yes", "on"}
PRESET_SMTP = {"host": "smtp.163.com", "port": "465"}


def inspect_smtp_config() -> dict:
    from preferences import get_smtp_preferences

    prefs = get_smtp_preferences()
    use_default_config = parse_bool(os.environ.get("SMTP_USE_DEFAULT_CONFIG") or prefs.get("smtp_use_default_config"), default=True)
    default_env_path = Path(
        os.environ.get("SMTP_DEFAULT_ENV_PATH") or prefs.get("smtp_default_env_path", "") or str(get_default_smtp_env_path())
    ).expanduser()
    default_env_values = read_dotenv_values(default_env_path) if use_default_config and default_env_path.exists() else {}
    resolved, source = _resolve_smtp_values(prefs, default_env_values)
    missing_fields = [name for name in ("username", "password") if not str(resolved[name]).strip()]
    return {
        "ready": not missing_fields,
        "message": build_missing_smtp_message(missing_fields, use_default_config, default_env_path),
        "use_default_config": use_default_config,
        "default_env_path": str(default_env_path),
        "default_env_exists": default_env_path.exists(),
        "source": source,
        "missing_fields": missing_fields,
        "resolved": resolved,
    }


def load_dotenv(env_path: Optional[str]) -> None:
    if not env_path:
        return
    path = Path(env_path)
    if not path.exists():
        return
    for key, value in read_dotenv_values(path).items():
        if key not in os.environ:
            os.environ[key] = value


def read_dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = strip_quotes(value.strip())
    return values


def parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in TRUE_VALUES


def strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def public_resolved(resolved: dict[str, object]) -> dict[str, object]:
    return {
        "host": resolved["host"],
        "port": resolved["port"],
        "username": str(resolved["username"]),
        "from_addr": resolved["from_addr"],
        "use_ssl": resolved["use_ssl"],
        "starttls": resolved["starttls"],
    }


def build_missing_smtp_message(missing_fields: list[str], use_default_config: bool, default_env_path: Path) -> str:
    if not missing_fields:
        return "SMTP 配置可用"
    default_hint = ""
    if use_default_config and not default_env_path.exists():
        default_hint = (
            "\n\n当前已启用 smtp_use_default_config=true，但未找到默认 SMTP 配置文件:\n"
            f"  {default_env_path}\n"
            "你可以：\n"
            "  1) 创建该文件（KEY=VALUE 格式，建议 chmod 600）\n"
            "  2) 或在当前项目的 EXTEND.md 中设置 smtp_use_default_config: false"
        )
    return (
        "SMTP 凭据未配置，缺少字段: "
        f"{', '.join(missing_fields)}。\n"
        "请通过以下方式之一配置:\n"
        "  1. 创建当前项目 .wechat-bid-digest/EXTEND.md 并填写 smtp_username 和 smtp_password\n"
        "  2. 设置环境变量: SMTP_USERNAME, SMTP_PASSWORD\n"
        "运行 --doctor 查看配置状态。"
        f"{default_hint}"
    )


def _resolve_smtp_values(prefs: dict, default_env_values: dict[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    host, host_source = _pick_smtp_value("SMTP_HOST", prefs.get("smtp_host", ""), default_env_values.get("SMTP_HOST", ""), PRESET_SMTP["host"])
    port, port_source = _pick_smtp_value("SMTP_PORT", prefs.get("smtp_port", ""), default_env_values.get("SMTP_PORT", ""), PRESET_SMTP["port"])
    username, username_source = _pick_alias_value(("SMTP_USERNAME", "SMTP_USER"), prefs.get("smtp_username", ""), default_env_values)
    password, password_source = _pick_alias_value(("SMTP_PASSWORD", "SMTP_PASS"), prefs.get("smtp_password", ""), default_env_values)
    from_addr, from_source = _pick_smtp_value("SMTP_FROM", prefs.get("smtp_from", ""), default_env_values.get("SMTP_FROM", ""), str(username))
    ssl_value, ssl_source = _pick_alias_value(("SMTP_SSL", "SMTP_SECURE"), prefs.get("smtp_ssl", ""), default_env_values, fallback="true")
    starttls_value, starttls_source = _pick_alias_value(
        ("SMTP_STARTTLS", "SMTP_REQUIRE_TLS"), prefs.get("smtp_starttls", ""), default_env_values, fallback="false"
    )
    return (
        {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "from_addr": from_addr or username,
            "use_ssl": parse_bool(str(ssl_value), default=True),
            "starttls": parse_bool(str(starttls_value), default=False),
        },
        {
            "host": host_source,
            "port": port_source,
            "username": username_source,
            "password": password_source,
            "from_addr": from_source,
            "use_ssl": ssl_source,
            "starttls": starttls_source,
        },
    )


def _pick_smtp_value(env_key: str, pref_value: str, default_env_value: str, fallback: str) -> tuple[str, str]:
    env_value = os.environ.get(env_key, "").strip()
    if env_value:
        return env_value, "environment"
    if str(pref_value).strip():
        return str(pref_value).strip(), "preferences"
    if str(default_env_value).strip():
        return str(default_env_value).strip(), "default_env"
    return fallback, "preset"


def _pick_alias_value(
    env_keys: tuple[str, ...], pref_value: str, default_env_values: dict[str, str], *, fallback: str = ""
) -> tuple[str, str]:
    for env_key in env_keys:
        env_value = os.environ.get(env_key, "").strip()
        if env_value:
            return env_value, "environment"
    if str(pref_value).strip():
        return str(pref_value).strip(), "preferences"
    for env_key in env_keys:
        default_value = default_env_values.get(env_key, "").strip()
        if default_value:
            return default_value, "default_env"
    return fallback, "preset" if fallback else "missing"
