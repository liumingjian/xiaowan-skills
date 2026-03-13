#!/usr/bin/env python3
from __future__ import annotations

import unittest

from support import make_config, make_tender_record
from html_report import build_html


class HtmlReportTests(unittest.TestCase):
    def test_build_html_supports_table_layout(self) -> None:
        config = make_config()
        html = build_html(
            config.job.description,
            [],
            from_date="2026-03-09",
            to_date="2026-03-11",
            keywords=config.filters.keywords,
            layout="table",
        )
        self.assertIn("表格版邮件正文", html)
        self.assertIn("邮件格式：table", html)

    def test_build_html_supports_card_layout(self) -> None:
        config = make_config()
        html = build_html(
            config.job.description,
            [],
            from_date="2026-03-09",
            to_date="2026-03-11",
            keywords=config.filters.keywords,
            layout="card",
        )
        self.assertIn("卡片版日报", html)
        self.assertIn("邮件格式：card", html)

    def test_visible_fields_in_html(self) -> None:
        records = [make_tender_record()]
        html = build_html(
            "测试",
            records,
            from_date="2026-03-09",
            to_date="2026-03-11",
            keywords=("维保",),
            layout="hybrid",
            visible_fields=("project_name", "amount", "source_url"),
        )
        self.assertIn("预算", html)
        self.assertNotIn("项目编号", html)

    def test_empty_state_shows_keywords(self) -> None:
        html = build_html(
            "测试",
            [],
            from_date="2026-03-09",
            to_date="2026-03-11",
            keywords=("维保", "服务器"),
            layout="card",
        )
        self.assertIn("维保", html)
        self.assertIn("建议", html)


if __name__ == "__main__":
    unittest.main()
