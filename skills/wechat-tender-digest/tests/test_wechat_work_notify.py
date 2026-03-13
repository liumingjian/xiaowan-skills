#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import support  # noqa: F401  # adds scripts/ to sys.path

from wechat_work_notify import WeChatWorkNotifyPolicy, evaluate_wechat_work_notification


class WeChatWorkNotifyTests(unittest.TestCase):
    def test_notify_first_seen_then_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "notify_state.json"
            policy = WeChatWorkNotifyPolicy(cooldown_seconds=3600, escalate_after_seconds=86400, state_file=state_file)
            start = datetime(2026, 3, 13, 0, 0, 0)

            first = evaluate_wechat_work_notification(auth_status="expired", now=start, policy=policy)
            self.assertTrue(first.should_notify)
            self.assertEqual(first.reason, "first_seen")
            self.assertTrue(state_file.exists())
            self.assertIsNotNone(first.incident)
            self.assertEqual(getattr(first.incident, "notify_count", -1), 1)

            within = evaluate_wechat_work_notification(auth_status="expired", now=start + timedelta(minutes=30), policy=policy)
            self.assertFalse(within.should_notify)
            self.assertEqual(within.reason, "cooldown_active")
            self.assertIsNotNone(within.incident)
            self.assertEqual(getattr(within.incident, "notify_count", -1), 1)

            after = evaluate_wechat_work_notification(auth_status="expired", now=start + timedelta(hours=2), policy=policy)
            self.assertTrue(after.should_notify)
            self.assertEqual(after.reason, "cooldown_elapsed")
            self.assertIsNotNone(after.incident)
            self.assertEqual(getattr(after.incident, "notify_count", -1), 2)

    def test_healthy_clears_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "notify_state.json"
            policy = WeChatWorkNotifyPolicy(cooldown_seconds=0, escalate_after_seconds=0, state_file=state_file)
            now = datetime(2026, 3, 13, 0, 0, 0)

            _ = evaluate_wechat_work_notification(auth_status="expired", now=now, policy=policy)
            self.assertTrue(state_file.exists())

            healthy = evaluate_wechat_work_notification(auth_status="healthy", now=now + timedelta(minutes=1), policy=policy)
            self.assertFalse(healthy.should_notify)
            self.assertFalse(state_file.exists())

    def test_escalated_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "notify_state.json"
            policy = WeChatWorkNotifyPolicy(cooldown_seconds=0, escalate_after_seconds=3600, state_file=state_file)
            start = datetime(2026, 3, 13, 0, 0, 0)

            first = evaluate_wechat_work_notification(auth_status="unreachable", now=start, policy=policy)
            self.assertFalse(first.escalated)

            later = evaluate_wechat_work_notification(auth_status="unreachable", now=start + timedelta(hours=2), policy=policy)
            self.assertTrue(later.escalated)


if __name__ == "__main__":
    unittest.main()

