#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime
from pathlib import Path


RUN_CHECK_PATH = (
    Path(__file__).resolve().parents[1].parent / "wechat-tender-auth" / "scripts" / "run_check.py"
)


def load_run_check_module():
    spec = importlib.util.spec_from_file_location("wechat_tender_auth_run_check", RUN_CHECK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load run_check.py from {RUN_CHECK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthCheckRunnerTests(unittest.TestCase):
    def test_handle_notification_skips_send_during_cooldown(self) -> None:
        module = load_run_check_module()
        payload = {}
        sent = {"count": 0}

        class Decision:
            should_notify = False
            incident = None
            incident_age_seconds = None
            escalated = False

            def to_payload(self):
                return {"should_notify": False, "reason": "cooldown_active"}

        module._handle_notification(
            payload=payload,
            service_name="svc",
            auth_status="expired",
            timestamp="2026-03-13T13:10:00",
            now=datetime(2026, 3, 13, 13, 10, 0),
            get_prefs=lambda: {"wechat_work_webhook": "https://example.com", "wechat_work_action_url": "https://example.com/runbook"},
            build_policy=lambda _prefs: object(),
            evaluate=lambda **_kwargs: Decision(),
            build_config=lambda _prefs: object(),
            validate_url=lambda _url: {"ok": True},
            build_content=lambda **_kwargs: "unused",
            send_text=lambda **_kwargs: sent.__setitem__("count", sent["count"] + 1),
        )

        self.assertEqual(payload["wechat_work_notify_decision"]["reason"], "cooldown_active")
        self.assertFalse(payload["wechat_work_notified"])
        self.assertEqual(sent["count"], 0)
        self.assertNotIn("action_url_check", payload)

    def test_handle_notification_validates_action_url_before_send(self) -> None:
        module = load_run_check_module()
        payload = {}
        captured = {"content": None, "send_count": 0}

        class Decision:
            should_notify = True
            incident_age_seconds = 120
            escalated = False

            class Incident:
                first_seen = "2026-03-13T13:08:00"
                notify_count = 1

            incident = Incident()

            def to_payload(self):
                return {"should_notify": True, "reason": "first_seen"}

        class Config:
            webhook_url = "https://example.com"
            action_url = "https://example.com/runbook"
            mentioned_list = ()
            mentioned_mobile_list = ()

        def build_content(**kwargs):
            captured["content"] = kwargs
            return "content"

        def send_text(**_kwargs):
            captured["send_count"] += 1

        module._handle_notification(
            payload=payload,
            service_name="svc",
            auth_status="expired",
            timestamp="2026-03-13T13:10:00",
            now=datetime(2026, 3, 13, 13, 10, 0),
            get_prefs=lambda: {"wechat_work_webhook": "https://example.com", "wechat_work_action_url": "https://example.com/runbook"},
            build_policy=lambda _prefs: object(),
            evaluate=lambda **_kwargs: Decision(),
            build_config=lambda _prefs: Config(),
            validate_url=lambda _url: {"ok": True, "reason": "ok", "status_code": 200},
            build_content=build_content,
            send_text=send_text,
        )

        self.assertTrue(payload["wechat_work_notified"])
        self.assertEqual(payload["action_url_check"]["status_code"], 200)
        self.assertIsNotNone(captured["content"])
        self.assertEqual(captured["content"]["action_url_check"]["reason"], "ok")
        self.assertEqual(captured["send_count"], 1)


if __name__ == "__main__":
    unittest.main()
