#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import SCRIPTS

from config_resolver import build_config_from_cli, build_config_from_preset
from doctor import build_doctor_payload
from friendly_setup import create_default_job, default_job_candidates, render_job_yaml, resolve_job_path
from job_creator import handle_create_job
from job_config import SourceSection, load_job_config
from project_paths import get_project_app_dir
from preferences import _parse_extend_md, load_preferences
from presets import get_preset, list_presets
from visible_fields import FIELD_SET_TO_FIELDS


class ConfigTests(unittest.TestCase):
    def test_preferences_parse_extend_md(self) -> None:
        text = """# User Preferences

## SMTP
- smtp_host: smtp.163.com
- smtp_port: 465
- smtp_username: user@163.com
- smtp_password: test_pass

## Defaults
- default_accounts: 七小服, 天下观查
- default_layout: hybrid
"""
        prefs = _parse_extend_md(text)
        self.assertEqual(prefs["smtp_host"], "smtp.163.com")
        self.assertEqual(prefs["smtp_port"], "465")
        self.assertEqual(prefs["smtp_username"], "user@163.com")
        self.assertEqual(prefs["default_accounts"], "七小服, 天下观查")
        self.assertEqual(prefs["default_layout"], "hybrid")

    def test_preferences_env_override(self) -> None:
        old_env = os.environ.get("SMTP_HOST")
        try:
            os.environ["SMTP_HOST"] = "override.example.com"
            prefs = load_preferences()
            self.assertEqual(prefs.get("smtp_host"), "override.example.com")
        finally:
            if old_env is None:
                os.environ.pop("SMTP_HOST", None)
            else:
                os.environ["SMTP_HOST"] = old_env

    def test_preferences_read_project_extend_md_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / ".wechat-bid-digest"
            app_dir.mkdir(parents=True, exist_ok=True)
            extend_path = app_dir / "EXTEND.md"
            extend_path.write_text("## SMTP\n- smtp_host: project.example.com\n", encoding="utf-8")
            original_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)
                prefs = load_preferences()
            finally:
                os.chdir(original_cwd)
        self.assertEqual(prefs.get("smtp_host"), "project.example.com")

    def test_presets_available(self) -> None:
        presets = list_presets()
        self.assertEqual(len(presets), 4)
        xinc = get_preset("xinc")
        self.assertIn("信创", xinc.keywords)
        hardware = get_preset("hardware")
        self.assertIn("维保", hardware.keywords)
        software = get_preset("software")
        self.assertIn("软件", software.keywords)
        eng = get_preset("engineering")
        self.assertIn("工程", eng.keywords)

    def test_preset_unknown_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            get_preset("nonexistent")

    def test_build_config_from_preset(self) -> None:
        import argparse

        args = argparse.Namespace(
            preset="xinc",
            accounts="测试公众号,另一个",
            to="test@example.com",
            layout=None,
            keywords=None,
            categories=None,
            window_days=None,
            job=None,
        )
        config = build_config_from_preset(args)
        self.assertEqual(config.source.accounts, ("测试公众号", "另一个"))
        self.assertEqual(config.email.to, ("test@example.com",))
        self.assertIn("信创", config.filters.keywords[0])
        self.assertEqual(config.email.layout, "hybrid")

    def test_field_set_core_sets_visible_fields(self) -> None:
        import argparse

        args = argparse.Namespace(
            accounts="测试公众号",
            keywords=None,
            categories=None,
            window_days=None,
            to=None,
            layout=None,
            field_set="core",
            visible_fields=None,
        )
        config = build_config_from_cli(args)
        self.assertEqual(config.email.visible_fields, FIELD_SET_TO_FIELDS["core"])

    def test_visible_fields_overrides_field_set(self) -> None:
        import argparse

        args = argparse.Namespace(
            accounts="测试公众号",
            keywords=None,
            categories=None,
            window_days=None,
            to=None,
            layout=None,
            field_set="core",
            visible_fields="project_name,amount",
        )
        config = build_config_from_cli(args)
        self.assertEqual(config.email.visible_fields, ("project_name", "amount"))

    def test_visible_fields_invalid_key_raises(self) -> None:
        import argparse

        args = argparse.Namespace(
            accounts="测试公众号",
            keywords=None,
            categories=None,
            window_days=None,
            to=None,
            layout=None,
            field_set=None,
            visible_fields="not_a_field",
        )
        with self.assertRaises(ValueError):
            build_config_from_cli(args)

    def test_create_job_writes_visible_fields(self) -> None:
        import argparse
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                args = argparse.Namespace(
                    accounts="测试公众号",
                    to="test@example.com",
                    preset=None,
                    layout=None,
                    field_set="minimal",
                    visible_fields=None,
                )
                path = handle_create_job(args)
                config = load_job_config(str(path))
                self.assertEqual(config.email.visible_fields, FIELD_SET_TO_FIELDS["minimal"])
            finally:
                os.chdir(original_cwd)

    def test_setup_yaml_no_gateway_fields(self) -> None:
        yaml_text = render_job_yaml(
            job_name="daily-bid",
            description="日报",
            window_days="3",
            accounts=("七小服",),
            keywords=("维保", "服务器"),
            recipients=(),
            email_enabled=False,
            email_layout="table",
            send_on_empty=False,
            subject="测试",
            output_root="wechat-bid-digest",
            report_filename="daily-bid-report.html",
            visible_fields=(),
        )
        self.assertIn("to: []", yaml_text)
        self.assertIn('layout: "table"', yaml_text)
        self.assertNotIn("gateway_mode", yaml_text)
        self.assertNotIn("docker_compose", yaml_text)
        self.assertNotIn("base_url", yaml_text)

    def test_setup_yaml_and_job_resolution(self) -> None:
        yaml_text = render_job_yaml(
            job_name="daily-bid",
            description="日报",
            window_days="3",
            accounts=("七小服",),
            keywords=("维保", "服务器"),
            recipients=(),
            email_enabled=False,
            email_layout="table",
            send_on_empty=False,
            subject="测试",
            output_root="wechat-bid-digest",
            report_filename="daily-bid-report.html",
            visible_fields=(),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = default_job_candidates(Path(tmpdir))[0]
            project_path.parent.mkdir(parents=True, exist_ok=True)
            project_path.write_text(yaml_text, encoding="utf-8")
            self.assertEqual(resolve_job_path(None, Path(tmpdir)), project_path)

    def test_load_job_config_backward_compat(self) -> None:
        old_yaml = """job:
  name: "test"
  description: "test"
  window_days: 3

source:
  gateway_mode: "auto"
  base_url_env: "WECHAT_GATEWAY_BASE_URL"
  default_base_url: "http://localhost:8080"
  base_url: null
  docker_compose_path: "docker-compose.yml"
  auto_start_docker: true
  accounts:
    - "七小服"
  limit_per_account: 10

filters:
  keywords:
    - "维保"
  categories:
    - "招标"
  sort_by: "publish_date_desc"

output:
  root_dir: "wechat-bid-digest"
  keep_raw: true
  keep_parsed: true
  keep_report: true
  report_filename: "test.html"

email:
  enabled: false
  send_on_empty: false
  layout: "table"
  subject: "test"
  to: []
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.yaml"
            path.write_text(old_yaml, encoding="utf-8")
            config = load_job_config(str(path))
            self.assertEqual(config.source.accounts, ("七小服",))
            self.assertEqual(config.source.limit_per_account, 10)

    def test_doctor_works_without_job_config(self) -> None:
        smtp_env = {
            "SMTP_USE_DEFAULT_CONFIG": "false",
            "SMTP_DEFAULT_ENV_PATH": "",
            "SMTP_HOST": "",
            "SMTP_PORT": "",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
            "SMTP_USER": "",
            "SMTP_PASS": "",
            "SMTP_FROM": "",
            "SMTP_SSL": "",
            "SMTP_SECURE": "",
            "SMTP_STARTTLS": "",
            "SMTP_REQUIRE_TLS": "",
            "SMTP_CONNECTION_TIMEOUT_MS": "",
            "SMTP_GREETING_TIMEOUT_MS": "",
            "SMTP_SOCKET_TIMEOUT_MS": "",
        }
        with patch.dict(os.environ, smtp_env, clear=False):
            with tempfile.TemporaryDirectory() as tmpdir:
                original_cwd = Path.cwd()
                try:
                    os.chdir(tmpdir)
                    payload = build_doctor_payload(None)
                finally:
                    os.chdir(original_cwd)
        self.assertEqual(payload["event"], "doctor_completed")
        self.assertIsNone(payload["job_path"])
        self.assertIn("auth", payload)
        self.assertFalse(payload["auth"]["ready"])
        self.assertTrue(payload["auth"]["qrcode_path"].endswith(".wechat-bid-digest/auth/qrcode.png"))
        self.assertIn("smtp", payload)
        self.assertFalse(payload["smtp"]["ready"])
        self.assertIn("default_env_path", payload["smtp"])
        self.assertIn("source", payload["smtp"])

    def test_create_default_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = create_default_job(
                ("测试公众号",),
                recipients=("test@example.com",),
                keywords=("维保", "服务器"),
                job_name="test-job",
                cwd=Path(tmpdir),
            )
            self.assertTrue(path.exists())
            config = load_job_config(str(path))
            self.assertEqual(config.source.accounts, ("测试公众号",))
            self.assertEqual(config.email.to, ("test@example.com",))
            self.assertEqual(path.parent, get_project_app_dir(Path(tmpdir)) / "jobs")

    def test_source_section_simplified(self) -> None:
        source = SourceSection(accounts=("七小服",), limit_per_account=10)
        self.assertEqual(source.accounts, ("七小服",))
        self.assertEqual(source.limit_per_account, 10)
        self.assertFalse(hasattr(source, "gateway_mode"))
        self.assertFalse(hasattr(source, "docker_compose_path"))

    def test_smtp_config_no_hardcoded_credentials(self) -> None:
        smtp_path = SCRIPTS / "smtp_sender.py"
        content = smtp_path.read_text(encoding="utf-8")
        self.assertNotIn("WPT9FgJ", content)
        self.assertNotIn("15521328037", content)
        self.assertNotIn("DEFAULT_HOST", content)
        self.assertNotIn("DEFAULT_USER", content)
        self.assertNotIn("DEFAULT_PASS", content)


if __name__ == "__main__":
    unittest.main()
