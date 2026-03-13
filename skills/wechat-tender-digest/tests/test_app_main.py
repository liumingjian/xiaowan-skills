#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import Mock, patch

import support  # noqa: F401  # adds scripts/ to sys.path

import app_main
from wechat_auth import AuthState


class AppMainTests(unittest.TestCase):
    def test_handle_login_outputs_qrcode_path(self) -> None:
        state = AuthState(token="abc", login_time="2026-03-13T18:00:00", expires_at="2026-03-17T18:00:00")
        fake_store = Mock()
        with patch.object(app_main, "AuthStore", return_value=fake_store):
            with patch.object(app_main, "qr_login_flow", return_value=state):
                with patch("sys.stdout", new=io.StringIO()) as stdout:
                    code = app_main._handle_login()
        payload = json.loads(stdout.getvalue().strip())
        self.assertEqual(code, 0)
        self.assertEqual(payload["event"], "login_completed")
        self.assertTrue(payload["qrcode_path"].endswith(".wechat-bid-digest/auth/qrcode.png"))
        self.assertTrue(payload["auth_state_path"].endswith(".wechat-bid-digest/auth/state.json"))
        fake_store.save.assert_called_once_with(state)
