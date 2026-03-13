from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from support import ROOT  # noqa: F401


class _FakeStore:
    def __init__(self) -> None:
        self.saved = []

    def save(self, state) -> None:
        self.saved.append(state)


class TestMobileRenewalAgent(unittest.TestCase):
    def setUp(self) -> None:
        from mobile_renewal_agent import AgentOptions
        from mobile_renewal_config import MobileRenewalConfig

        self.options = AgentOptions(once=True, poll_interval_seconds=1, confirm_timeout_seconds=0)
        self.config = MobileRenewalConfig(
            mode="spike",
            worker_url="https://worker",
            host_id="host-1",
            shared_secret="secret",
            request_ttl_seconds=600,
        )

    @patch("mobile_renewal_agent.poll_host", return_value=None)
    def test_run_once_no_request(self, _poll) -> None:
        from mobile_renewal_agent import run_once

        payload = run_once(options=self.options, config=self.config, store=_FakeStore())
        self.assertEqual(payload["event"], "no_request")

    @patch("mobile_renewal_agent.report_result")
    @patch("mobile_renewal_agent.upload_mobile_payload")
    @patch("mobile_renewal_agent.wait_for_login_token", return_value="tok")
    @patch("mobile_renewal_agent.build_auth_state")
    @patch("mobile_renewal_agent.begin_qr_login")
    @patch("mobile_renewal_agent.poll_host")
    def test_run_once_confirmed(
        self,
        poll_host: Mock,
        begin_qr_login: Mock,
        build_auth_state: Mock,
        _wait_for_token: Mock,
        upload_mobile_payload: Mock,
        report_result: Mock,
    ) -> None:
        from mobile_renewal_agent import run_once
        from mobile_renewal_worker_client import HostPolledRequest
        from wechat_auth import AuthState

        poll_host.return_value = HostPolledRequest(
            request_id="req_1",
            token="tok_1",
            host_id="host-1",
            expires_at="2026-03-13T00:10:00Z",
            status="preparing_mobile_flow",
        )
        begin_qr_login.return_value = Mock(qr_png_bytes=b"png", session=Mock())
        build_auth_state.return_value = AuthState(cookies={}, token="tok", login_time="t1", expires_at="t2")
        store = _FakeStore()

        payload = run_once(options=self.options, config=self.config, store=store)
        self.assertEqual(payload["event"], "renewal_confirmed")
        self.assertEqual(store.saved[0].token, "tok")
        upload_mobile_payload.assert_called_once()
        report_result.assert_called_once()

    @patch("mobile_renewal_agent.report_result")
    @patch("mobile_renewal_agent.upload_mobile_payload")
    @patch("mobile_renewal_agent.wait_for_login_token", side_effect=Exception("boom"))
    @patch("mobile_renewal_agent.begin_qr_login")
    @patch("mobile_renewal_agent.poll_host")
    def test_unexpected_exception_bubbles_up(
        self,
        poll_host: Mock,
        begin_qr_login: Mock,
        _wait_for_token: Mock,
        upload_mobile_payload: Mock,
        report_result: Mock,
    ) -> None:
        from mobile_renewal_agent import run_once
        from mobile_renewal_worker_client import HostPolledRequest

        poll_host.return_value = HostPolledRequest(
            request_id="req_1",
            token="tok_1",
            host_id="host-1",
            expires_at="2026-03-13T00:10:00Z",
            status="preparing_mobile_flow",
        )
        begin_qr_login.return_value = Mock(qr_png_bytes=b"png", session=Mock())

        # Unexpected exception should bubble up (debug-first), so we expect the test to raise.
        with self.assertRaises(Exception):
            run_once(options=self.options, config=self.config, store=_FakeStore())

        upload_mobile_payload.assert_called_once()
        report_result.assert_not_called()

    @patch("mobile_renewal_agent.report_result")
    @patch("mobile_renewal_agent.upload_mobile_payload")
    @patch("mobile_renewal_agent.wait_for_login_token")
    @patch("mobile_renewal_agent.begin_qr_login")
    @patch("mobile_renewal_agent.poll_host")
    def test_timeout_reports_expired(
        self,
        poll_host: Mock,
        begin_qr_login: Mock,
        wait_for_login_token: Mock,
        _upload: Mock,
        report_result: Mock,
    ) -> None:
        from mobile_renewal_agent import run_once
        from mobile_renewal_worker_client import HostPolledRequest
        from wechat_mp_qr_login import WeChatLoginTimeout

        poll_host.return_value = HostPolledRequest(
            request_id="req_1",
            token="tok_1",
            host_id="host-1",
            expires_at="2026-03-13T00:10:00Z",
            status="preparing_mobile_flow",
        )
        begin_qr_login.return_value = Mock(qr_png_bytes=b"png", session=Mock())
        wait_for_login_token.side_effect = WeChatLoginTimeout("timeout")

        payload = run_once(options=self.options, config=self.config, store=_FakeStore())
        self.assertEqual(payload["event"], "renewal_expired")
        report_result.assert_called_once()

    @patch("mobile_renewal_agent.report_result")
    @patch("mobile_renewal_agent.upload_mobile_payload")
    @patch("mobile_renewal_agent.wait_for_login_token")
    @patch("mobile_renewal_agent.begin_qr_login")
    @patch("mobile_renewal_agent.poll_host")
    def test_login_error_reports_failed(
        self,
        poll_host: Mock,
        begin_qr_login: Mock,
        wait_for_login_token: Mock,
        _upload: Mock,
        report_result: Mock,
    ) -> None:
        from mobile_renewal_agent import run_once
        from mobile_renewal_worker_client import HostPolledRequest
        from wechat_auth import LoginError

        poll_host.return_value = HostPolledRequest(
            request_id="req_1",
            token="tok_1",
            host_id="host-1",
            expires_at="2026-03-13T00:10:00Z",
            status="preparing_mobile_flow",
        )
        begin_qr_login.return_value = Mock(qr_png_bytes=b"png", session=Mock())
        wait_for_login_token.side_effect = LoginError("cancelled")

        payload = run_once(options=self.options, config=self.config, store=_FakeStore())
        self.assertEqual(payload["event"], "renewal_failed")
        report_result.assert_called_once()


if __name__ == "__main__":
    unittest.main()
