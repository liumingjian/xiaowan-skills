#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Optional


TRUE_VALUES = {"1", "true", "yes", "on"}
APP_DIR_NAME = ".wechat-bid-digest"
DEFAULT_SMTP_ENV_FILENAME = "smtp-default.env"
DEFAULT_SMTP_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    use_ssl: bool
    starttls: bool
    username: str
    password: str
    from_addr: str
    timeout: int


class SmtpError(Exception):
    pass


def send_html_email(html_body: str, recipients: tuple[str, ...], subject: str, *, env_path: Optional[str] = None) -> dict:
    load_dotenv(env_path)
    config = load_smtp_config()
    message = build_message(html_body, recipients, subject, from_addr=config.from_addr)
    try:
        deliver_message(message, recipients, config)
    except (smtplib.SMTPException, OSError) as error:
        raise SmtpError(f"SMTP 发送失败 ({config.host}:{config.port}): {error}") from error
    return {
        "type": "status",
        "event": "email_sent",
        "subject": subject,
        "to": list(recipients),
        "smtp_host": config.host,
        "smtp_port": config.port,
        "message_id": message["Message-ID"],
    }


def test_smtp_connection(env_path: Optional[str] = None) -> dict:
    """Test SMTP connectivity without sending an email."""
    load_dotenv(env_path)
    try:
        config = load_smtp_config()
    except ValueError as error:
        return {"healthy": False, "error": str(error), "stage": "config"}
    try:
        context = ssl.create_default_context()
        if config.use_ssl:
            with smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=context) as client:
                client.login(config.username, config.password)
        else:
            with smtplib.SMTP(config.host, config.port, timeout=config.timeout) as client:
                if config.starttls:
                    client.starttls(context=context)
                client.login(config.username, config.password)
        return {"healthy": True, "host": config.host, "port": config.port, "from_addr": config.from_addr}
    except (smtplib.SMTPException, OSError) as error:
        return {"healthy": False, "error": str(error), "stage": "connection", "host": config.host, "port": config.port}


def load_dotenv(env_path: Optional[str]) -> None:
    if not env_path:
        return
    path = Path(env_path)
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key and key not in os.environ:
            os.environ[key] = strip_quotes(value.strip())


def load_smtp_config() -> SmtpConfig:
    # Load from preferences (EXTEND.md) first, then env vars override
    from preferences import get_smtp_preferences
    prefs = get_smtp_preferences()

    use_default_config = parse_bool(
        os.environ.get("SMTP_USE_DEFAULT_CONFIG") or prefs.get("smtp_use_default_config"),
        default=True,
    )
    default_env_path = (
        os.environ.get("SMTP_DEFAULT_ENV_PATH")
        or prefs.get("smtp_default_env_path", "")
        or str(Path.home() / APP_DIR_NAME / DEFAULT_SMTP_ENV_FILENAME)
    )
    if use_default_config:
        load_dotenv(default_env_path)

    # Preset 163 SMTP config (host/port only, no credentials)
    PRESET_SMTP = {
        "host": "smtp.163.com",
        "port": "465",
    }

    host = os.environ.get("SMTP_HOST") or prefs.get("smtp_host", "") or PRESET_SMTP["host"]
    username = os.environ.get("SMTP_USERNAME") or os.environ.get("SMTP_USER") or prefs.get("smtp_username", "")
    password = os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS") or prefs.get("smtp_password", "")
    from_addr = (os.environ.get("SMTP_FROM") or prefs.get("smtp_from", "")).strip()

    if not username or not password:
        default_hint = ""
        env_path = Path(default_env_path).expanduser()
        if use_default_config and not env_path.exists():
            default_hint = (
                "\n\n当前已启用 smtp_use_default_config=true，但未找到默认 SMTP 配置文件:\n"
                f"  {env_path}\n"
                "你可以：\n"
                "  1) 创建该文件（KEY=VALUE 格式，建议 chmod 600）\n"
                "  2) 或在 EXTEND.md 中设置 smtp_use_default_config: false（推广/公开发布建议关闭）"
            )
        raise ValueError(
            "SMTP 凭据未配置。请通过以下方式之一配置:\n"
            "  1. 创建 ~/.wechat-bid-digest/EXTEND.md 并填写 smtp_username 和 smtp_password\n"
            "  2. 设置环境变量: SMTP_USERNAME, SMTP_PASSWORD\n"
            "运行 --doctor 查看配置状态。"
            f"{default_hint}"
        )

    port_str = os.environ.get("SMTP_PORT") or prefs.get("smtp_port", "") or PRESET_SMTP["port"]

    timeout_seconds = _resolve_smtp_timeout_seconds()
    return SmtpConfig(
        host=host.strip(),
        port=int(port_str),
        use_ssl=parse_bool(os.environ.get("SMTP_SSL") or os.environ.get("SMTP_SECURE") or prefs.get("smtp_ssl"), default=True),
        starttls=parse_bool(os.environ.get("SMTP_STARTTLS") or os.environ.get("SMTP_REQUIRE_TLS") or prefs.get("smtp_starttls"), default=False),
        username=username.strip(),
        password=password.strip(),
        from_addr=from_addr or username.strip(),
        timeout=timeout_seconds,
    )


def build_message(html_body: str, recipients: tuple[str, ...], subject: str, *, from_addr: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message["Message-ID"] = make_msgid()
    message.set_content("This message requires an HTML-compatible mail client.")
    message.add_alternative(html_body, subtype="html")
    return message


def deliver_message(message: EmailMessage, recipients: tuple[str, ...], config: SmtpConfig) -> None:
    context = ssl.create_default_context()
    if config.use_ssl:
        with smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=context) as client:
            client.login(config.username, config.password)
            client.send_message(message, to_addrs=list(recipients))
        return
    with smtplib.SMTP(config.host, config.port, timeout=config.timeout) as client:
        if config.starttls:
            client.starttls(context=context)
        client.login(config.username, config.password)
        client.send_message(message, to_addrs=list(recipients))


def write_send_result(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return strip_quotes(value)


def parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in TRUE_VALUES


def strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _resolve_smtp_timeout_seconds() -> int:
    values = [
        os.environ.get("SMTP_SOCKET_TIMEOUT_MS", ""),
        os.environ.get("SMTP_GREETING_TIMEOUT_MS", ""),
        os.environ.get("SMTP_CONNECTION_TIMEOUT_MS", ""),
        os.environ.get("SMTP_CONNECT_TIMEOUT", ""),
        os.environ.get("SMTP_CONNECTION_TIMEOUT", ""),
    ]
    for raw in values:
        if raw and raw.strip():
            return max(1, int(raw.strip()) // 1000)
    return DEFAULT_SMTP_TIMEOUT_SECONDS
