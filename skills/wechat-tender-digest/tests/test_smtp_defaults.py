#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  # adds scripts/ to sys.path

from smtp_sender import load_smtp_config


SMTP_ENV_KEYS = (
    "SMTP_USE_DEFAULT_CONFIG",
    "SMTP_DEFAULT_ENV_PATH",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_SSL",
    "SMTP_SECURE",
    "SMTP_STARTTLS",
    "SMTP_REQUIRE_TLS",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_USER",
    "SMTP_PASS",
    "SMTP_FROM",
    "SMTP_CONNECTION_TIMEOUT_MS",
    "SMTP_GREETING_TIMEOUT_MS",
    "SMTP_SOCKET_TIMEOUT_MS",
    "SMTP_CONNECT_TIMEOUT",
    "SMTP_CONNECTION_TIMEOUT",
)


class SmtpDefaultsTests(unittest.TestCase):
    def test_load_smtp_config_reads_default_env_file_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "smtp-default.env"
            env_path.write_text(
                "\n".join(
                    [
                        "SMTP_HOST=smtp.example.com",
                        "SMTP_PORT=465",
                        "SMTP_SECURE=true",
                        "SMTP_REQUIRE_TLS=false",
                        "SMTP_CONNECTION_TIMEOUT_MS=10000",
                        "SMTP_GREETING_TIMEOUT_MS=10000",
                        "SMTP_SOCKET_TIMEOUT_MS=15000",
                        "SMTP_USER=user@example.com",
                        "SMTP_PASS=pass123",
                        "SMTP_FROM=user@example.com",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            old = {k: os.environ.get(k) for k in SMTP_ENV_KEYS}
            try:
                for k in SMTP_ENV_KEYS:
                    os.environ.pop(k, None)
                os.environ["SMTP_USE_DEFAULT_CONFIG"] = "true"
                os.environ["SMTP_DEFAULT_ENV_PATH"] = str(env_path)
                config = load_smtp_config()
                self.assertEqual(config.host, "smtp.example.com")
                self.assertEqual(config.port, 465)
                self.assertEqual(config.username, "user@example.com")
                self.assertEqual(config.password, "pass123")
                self.assertEqual(config.from_addr, "user@example.com")
                self.assertEqual(config.timeout, 15)
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_load_smtp_config_does_not_read_default_env_file_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "smtp-default.env"
            env_path.write_text("SMTP_USER=user@example.com\nSMTP_PASS=pass123\n", encoding="utf-8")

            old = {k: os.environ.get(k) for k in SMTP_ENV_KEYS}
            try:
                for k in SMTP_ENV_KEYS:
                    os.environ.pop(k, None)
                os.environ["SMTP_USE_DEFAULT_CONFIG"] = "false"
                os.environ["SMTP_DEFAULT_ENV_PATH"] = str(env_path)
                with self.assertRaises(ValueError):
                    load_smtp_config()
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()

