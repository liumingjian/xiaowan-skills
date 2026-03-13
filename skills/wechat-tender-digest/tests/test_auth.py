#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
import os
from datetime import datetime, timedelta
from pathlib import Path

import support  # noqa: F401  # adds scripts/ to sys.path

import wechat_auth
from auth_manager import AuthManager, AuthManagerError
from auth_daemon import _build_status_payload
from auth_manager import AuthCheckResult
from job_pipeline import ensure_healthy
from project_paths import get_auth_state_file
from wechat_auth import AuthState, AuthStore
from wechat_client import WeChatError


class AuthTests(unittest.TestCase):
    def test_auth_expired_raises_wechat_error(self) -> None:
        with self.assertRaises(WeChatError) as context:
            ensure_healthy({"authStatus": "expired"})
        self.assertEqual(context.exception.event, "auth_expired")
        self.assertIn("过期", str(context.exception))

    def test_auth_unreachable_raises_wechat_error(self) -> None:
        with self.assertRaises(WeChatError) as context:
            ensure_healthy({"authStatus": "unreachable"})
        self.assertEqual(context.exception.event, "auth_unhealthy")

    def test_auth_healthy_passes(self) -> None:
        ensure_healthy({"authStatus": "healthy"})

    def test_auth_store_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            store = AuthStore(path)

            state = store.load()
            self.assertFalse(state.is_valid())
            self.assertEqual(state.token, "")

            now = datetime.now()
            state = AuthState(
                cookies={"key": "value"},
                token="test_token_123",
                login_time=now.isoformat(),
                expires_at=(now + timedelta(hours=4)).isoformat(),
            )
            store.save(state)
            self.assertTrue(path.exists())

            loaded = store.load()
            self.assertEqual(loaded.token, "test_token_123")
            self.assertEqual(loaded.cookies, {"key": "value"})
            self.assertTrue(loaded.is_valid())

    def test_auth_store_defaults_to_project_scoped_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)
                store = AuthStore()
            finally:
                os.chdir(original_cwd)
        self.assertEqual(store.path.resolve(), get_auth_state_file(Path(tmpdir)).resolve())

    def test_auth_state_expired(self) -> None:
        past = datetime.now() - timedelta(hours=1)
        state = AuthState(
            cookies={},
            token="old_token",
            login_time=(past - timedelta(hours=4)).isoformat(),
            expires_at=past.isoformat(),
        )
        self.assertFalse(state.is_valid())

    def test_auth_manager_health_healthy_skips_login(self) -> None:
        class State:
            def __init__(self) -> None:
                self.token = "old"
                self.expires_at = "2000-01-01T00:00:00"

        class Store:
            def __init__(self, state: State) -> None:
                self._state = state
                self.saved = 0

            def load(self) -> State:
                return self._state

            def save(self, state: State) -> None:
                self._state = state
                self.saved += 1

        class Client:
            def health(self):
                return {"authStatus": "healthy"}

        state = State()
        store = Store(state)
        login_called = {"count": 0}

        def login_flow():
            login_called["count"] += 1
            new = State()
            new.token = "new"
            return new

        fixed_now = datetime(2026, 3, 13, 0, 0, 0)
        manager = AuthManager(store, login_flow=login_flow, client_factory=lambda _s: Client(), now=lambda: fixed_now)
        result = manager.check_and_refresh()
        self.assertFalse(result.refreshed)
        self.assertEqual(login_called["count"], 0)
        self.assertGreater(store.saved, 0)

    def test_auth_manager_refreshes_on_expired(self) -> None:
        class State:
            def __init__(self, token: str) -> None:
                self.token = token
                self.expires_at = "2000-01-01T00:00:00"

        class Store:
            def __init__(self, state: State) -> None:
                self._state = state
                self.saved_states = []

            def load(self) -> State:
                return self._state

            def save(self, state: State) -> None:
                self._state = state
                self.saved_states.append(state.token)

        class ClientSeq:
            def __init__(self, statuses):
                self._statuses = list(statuses)

            def health(self):
                return {"authStatus": self._statuses.pop(0)}

        client = ClientSeq(["expired", "healthy"])
        store = Store(State("old"))
        login_called = {"count": 0}

        def login_flow():
            login_called["count"] += 1
            return State("new")

        manager = AuthManager(store, login_flow=login_flow, client_factory=lambda _s: client, now=lambda: datetime(2026, 3, 13, 0, 0, 0))
        result = manager.check_and_refresh()
        self.assertTrue(result.refreshed)
        self.assertEqual(login_called["count"], 1)
        self.assertEqual(store._state.token, "new")

    def test_auth_manager_raises_on_unreachable(self) -> None:
        class State:
            def __init__(self) -> None:
                self.token = "t"
                self.expires_at = "2000-01-01T00:00:00"

        class Store:
            def __init__(self, state: State) -> None:
                self._state = state

            def load(self) -> State:
                return self._state

            def save(self, state: State) -> None:
                self._state = state

        class Client:
            def health(self):
                return {"authStatus": "unreachable"}

        manager = AuthManager(Store(State()), login_flow=lambda: State(), client_factory=lambda _s: Client())
        with self.assertRaises(AuthManagerError) as ctx:
            manager.check_and_refresh()
        self.assertEqual(ctx.exception.event, "auth_unreachable")

    def test_auth_daemon_status_payload_events(self) -> None:
        class State:
            def __init__(self) -> None:
                self.expires_at = "2026-03-13T04:00:00"

        refreshed = AuthCheckResult(state=State(), health={"authStatus": "healthy"}, refreshed=True)
        healthy = AuthCheckResult(state=State(), health={"authStatus": "healthy"}, refreshed=False)
        self.assertEqual(_build_status_payload(refreshed, "t")["event"], "auth_refreshed")
        self.assertEqual(_build_status_payload(healthy, "t")["event"], "auth_healthy")

    def test_display_qr_code_saves_png_and_renders_terminal(self) -> None:
        original_renderer = wechat_auth._render_qr_to_terminal
        original_save_png = wechat_auth._save_qr_png
        calls = {"rendered": 0}
        saved = {"count": 0}

        try:
            def fake_render(image_data: bytes) -> None:
                self.assertEqual(image_data, b"fake-png")
                calls["rendered"] += 1

            def record_save_png(_image_data: bytes) -> Path:
                saved["count"] += 1
                return Path("/tmp/qrcode.png")

            wechat_auth._render_qr_to_terminal = fake_render
            wechat_auth._save_qr_png = record_save_png
            wechat_auth._display_qr_code(b"fake-png")
            self.assertEqual(calls["rendered"], 1)
            self.assertEqual(saved["count"], 1)
        finally:
            wechat_auth._render_qr_to_terminal = original_renderer
            wechat_auth._save_qr_png = original_save_png


if __name__ == "__main__":
    unittest.main()
