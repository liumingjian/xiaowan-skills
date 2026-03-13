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

from smtp_config_state import inspect_smtp_config, load_dotenv, public_resolved


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
    load_dotenv(env_path)
    details = inspect_smtp_config()
    if not details["ready"]:
        return _build_config_error(details)
    config = load_smtp_config()
    try:
        _login_smtp(config)
        return _build_connection_result(details, healthy=True, error="")
    except (smtplib.SMTPException, OSError) as error:
        return _build_connection_result(details, healthy=False, error=str(error))


def load_smtp_config() -> SmtpConfig:
    details = inspect_smtp_config()
    if not details["ready"]:
        raise ValueError(str(details["message"]))
    if details["use_default_config"] and details["default_env_exists"]:
        load_dotenv(str(details["default_env_path"]))
    resolved = details["resolved"]
    return SmtpConfig(
        host=str(resolved["host"]).strip(),
        port=int(resolved["port"]),
        use_ssl=bool(resolved["use_ssl"]),
        starttls=bool(resolved["starttls"]),
        username=str(resolved["username"]).strip(),
        password=str(resolved["password"]).strip(),
        from_addr=str(resolved["from_addr"]).strip(),
        timeout=_resolve_smtp_timeout_seconds(),
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
    _login_smtp(config, message=message, recipients=recipients)


def write_send_result(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_config_error(details: dict) -> dict:
    return {
        "healthy": False,
        "ready": False,
        "stage": "config",
        "error": details["message"],
        "missing_fields": details["missing_fields"],
        "source": details["source"],
        "use_default_config": details["use_default_config"],
        "default_env_path": details["default_env_path"],
        "default_env_exists": details["default_env_exists"],
        "resolved": public_resolved(details["resolved"]),
    }


def _build_connection_result(details: dict, *, healthy: bool, error: str) -> dict:
    result = {
        "healthy": healthy,
        "ready": True,
        "host": details["resolved"]["host"],
        "port": int(details["resolved"]["port"]),
        "from_addr": details["resolved"]["from_addr"],
        "source": details["source"],
        "use_default_config": details["use_default_config"],
        "default_env_path": details["default_env_path"],
        "default_env_exists": details["default_env_exists"],
        "missing_fields": [],
        "resolved": public_resolved(details["resolved"]),
    }
    if not healthy:
        result["stage"] = "connection"
        result["error"] = error
    return result


def _login_smtp(
    config: SmtpConfig, *, message: Optional[EmailMessage] = None, recipients: Optional[tuple[str, ...]] = None
) -> None:
    context = ssl.create_default_context()
    if config.use_ssl:
        with smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=context) as client:
            client.login(config.username, config.password)
            if message and recipients:
                client.send_message(message, to_addrs=list(recipients))
        return
    with smtplib.SMTP(config.host, config.port, timeout=config.timeout) as client:
        if config.starttls:
            client.starttls(context=context)
        client.login(config.username, config.password)
        if message and recipients:
            client.send_message(message, to_addrs=list(recipients))


def _resolve_smtp_timeout_seconds() -> int:
    values = (
        os.environ.get("SMTP_SOCKET_TIMEOUT_MS", ""),
        os.environ.get("SMTP_GREETING_TIMEOUT_MS", ""),
        os.environ.get("SMTP_CONNECTION_TIMEOUT_MS", ""),
        os.environ.get("SMTP_CONNECT_TIMEOUT", ""),
        os.environ.get("SMTP_CONNECTION_TIMEOUT", ""),
    )
    for raw in values:
        if raw and raw.strip():
            return max(1, int(raw.strip()) // 1000)
    return DEFAULT_SMTP_TIMEOUT_SECONDS
