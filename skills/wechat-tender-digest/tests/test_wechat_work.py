#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch

import requests
import support  # noqa: F401  # adds scripts/ to sys.path

from wechat_work import (
    build_reminder_content,
    build_wechat_work_config,
    send_wechat_work_text,
    validate_action_url,
)


class WeChatWorkTests(unittest.TestCase):
    def test_build_wechat_work_config_requires_webhook(self) -> None:
        with self.assertRaises(ValueError):
            build_wechat_work_config({})

    def test_build_wechat_work_config_requires_action_url(self) -> None:
        with self.assertRaises(ValueError):
            build_wechat_work_config({"wechat_work_webhook": "https://example.com"})

    def test_build_wechat_work_config_parses_mentions(self) -> None:
        cfg = build_wechat_work_config(
            {
                "wechat_work_webhook": "https://example.com",
                "wechat_work_action_url": "https://example.com/runbook",
                "wechat_work_mentioned_list": "@all, user1",
                "wechat_work_mentioned_mobile_list": "13800000000, 13900000000",
            }
        )
        self.assertEqual(cfg.mentioned_list, ("@all", "user1"))
        self.assertEqual(cfg.mentioned_mobile_list, ("13800000000", "13900000000"))

    def test_build_reminder_content_includes_link(self) -> None:
        content = build_reminder_content(
            service_name="svc",
            auth_status="expired",
            timestamp="2026-03-13T00:00:00",
            action_url="https://example.com/runbook",
        )
        self.assertIn("https://example.com/runbook", content)

    def test_build_reminder_content_includes_action_url_check(self) -> None:
        content = build_reminder_content(
            service_name="svc",
            auth_status="expired",
            timestamp="2026-03-13T00:00:00",
            action_url="https://example.com/runbook",
            action_url_check={"ok": True, "status_code": 200, "reason": "ok"},
        )
        self.assertIn("链接检查", content)
        self.assertIn("HTTP 200", content)

    def test_build_reminder_content_supports_incident_fields(self) -> None:
        content = build_reminder_content(
            service_name="svc",
            auth_status="expired",
            timestamp="2026-03-13T00:00:00",
            action_url="https://example.com/runbook",
            incident_first_seen="2026-03-12T00:00:00",
            incident_age_seconds=3600,
            notify_count=2,
            escalated=True,
        )
        self.assertIn("首次发现", content)
        self.assertIn("已持续", content)
        self.assertIn("已提醒", content)

    def test_validate_action_url_rejects_non_http_scheme(self) -> None:
        result = validate_action_url("file:///tmp/runbook")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid_url")

    def test_validate_action_url_accepts_http_200(self) -> None:
        class Resp:
            status_code = 200
            url = "https://example.com/runbook"

        with patch("wechat_work.requests.get", return_value=Resp()):
            result = validate_action_url("https://example.com/runbook")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)

    def test_validate_action_url_reports_request_failure(self) -> None:
        with patch("wechat_work.requests.get", side_effect=requests.RequestException("boom")):
            result = validate_action_url("https://example.com/runbook")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "request_failed")

    def test_send_wechat_work_text_builds_payload(self) -> None:
        class Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return {"errcode": 0, "errmsg": "ok"}

        with patch("wechat_work.requests.post", return_value=Resp()) as post:
            send_wechat_work_text(
                webhook_url="https://example.com",
                content="hello",
                mentioned_list=("@all",),
                mentioned_mobile_list=("13800000000",),
            )
            _args, kwargs = post.call_args
            payload = kwargs["json"]
            self.assertEqual(payload["msgtype"], "text")
            self.assertEqual(payload["text"]["content"], "hello")
            self.assertEqual(payload["text"]["mentioned_list"], ["@all"])
            self.assertEqual(payload["text"]["mentioned_mobile_list"], ["13800000000"])


if __name__ == "__main__":
    unittest.main()
