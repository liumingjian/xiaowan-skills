#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import make_config
from html_report import build_html
from job_fetch import fetch_articles
from job_pipeline import ensure_email_preflight, handle_send, resolve_dates
from output_paths import build_job_date_output_dir


class PipelineTests(unittest.TestCase):
    def test_resolve_dates_defaults_and_overrides(self) -> None:
        config = make_config()
        auto_from, auto_to = resolve_dates(config, None, None)
        self.assertLessEqual(auto_from, auto_to)
        manual_from, manual_to = resolve_dates(config, "2026-03-09", "2026-03-11")
        self.assertEqual((manual_from, manual_to), ("2026-03-09", "2026-03-11"))

    def test_empty_records_render_and_skip_send(self) -> None:
        config = make_config()
        html = build_html(
            config.job.description,
            [],
            from_date="2026-03-09",
            to_date="2026-03-11",
            keywords=config.filters.keywords,
        )
        self.assertIn("未检索到招标分类信息", html)
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = handle_send(
                config,
                Path(tmpdir),
                raw_articles=[],
                records=[],
                report_path=str(Path(tmpdir) / "report.html"),
                html_body=html,
                from_date="2026-03-09",
                to_date="2026-03-11",
                job_path="(test)",
                auth_info={"auth_status": "valid"},
            )
            self.assertEqual(payload["event"], "no_matching_records")
            self.assertFalse(payload["email_sent"])
            self.assertTrue((Path(tmpdir) / "send-result.json").exists())

    def test_output_dir_includes_job_name(self) -> None:
        out = build_job_date_output_dir(root_dir="wechat-bid-digest", job_name="demo job", to_date="2026-03-13")
        self.assertTrue(str(out).endswith("wechat-bid-digest/demo_job/2026-03-13"))

    def test_email_preflight_requires_ready_smtp(self) -> None:
        config = make_config()
        with patch("job_pipeline.inspect_smtp_config", return_value={"ready": False, "message": "missing creds"}):
            with self.assertRaisesRegex(ValueError, "邮件模式必须先运行 --doctor"):
                ensure_email_preflight(config)

    def test_fetch_articles_emits_progress_events(self) -> None:
        config = make_config()
        config = type(config)(
            job=config.job,
            source=config.source,
            filters=config.filters,
            output=type(config.output)(
                root_dir=config.output.root_dir,
                keep_raw=False,
                keep_parsed=config.output.keep_parsed,
                keep_report=config.output.keep_report,
                report_filename=config.output.report_filename,
            ),
            email=config.email,
        )

        class FakeAccount:
            fakeid = "fakeid"
            name = "七小服"

        class FakeClient:
            def resolve_accounts(self, accounts):
                return [FakeAccount()]

            def list_articles(self, account, from_date, to_date):
                return [{"title": "测试文章", "url": "https://example.com/a", "create_time": "1773193871"}]

            def download_article_html(self, url):
                return "<div id='js_content'>服务器维保项目</div>"

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("job_fetch.emit_progress") as emit_progress:
                raw_articles, fetch_errors = fetch_articles(
                    FakeClient(),
                    config,
                    from_date="2026-03-10",
                    to_date="2026-03-12",
                    output_dir=Path(tmpdir),
                )
        self.assertEqual(len(raw_articles), 1)
        self.assertFalse(fetch_errors)
        events = [call.args[0] for call in emit_progress.call_args_list]
        self.assertEqual(
            events,
            [
                "resolve_accounts_started",
                "resolve_accounts_completed",
                "list_articles_started",
                "list_articles_completed",
                "download_article_started",
                "download_article_completed",
            ],
        )


if __name__ == "__main__":
    unittest.main()
