#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support import make_config
from html_report import build_html
from job_pipeline import handle_send, resolve_dates
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


if __name__ == "__main__":
    unittest.main()
