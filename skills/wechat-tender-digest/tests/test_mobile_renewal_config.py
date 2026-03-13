from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from support import ROOT  # noqa: F401


class TestMobileRenewalConfig(unittest.TestCase):
    def test_default_mode_is_off(self) -> None:
        from mobile_renewal_config import build_mobile_renewal_config

        cfg = build_mobile_renewal_config({})
        self.assertEqual(cfg.mode, "off")

    def test_spike_requires_worker_url(self) -> None:
        from mobile_renewal_config import build_mobile_renewal_config

        with self.assertRaises(ValueError) as ctx:
            build_mobile_renewal_config({"mobile_renewal_mode": "spike"})
        self.assertIn("mobile_renewal_worker_url", str(ctx.exception))

    def test_spike_requires_http_url(self) -> None:
        from mobile_renewal_config import build_mobile_renewal_config

        with self.assertRaises(ValueError) as ctx:
            build_mobile_renewal_config(
                {
                    "mobile_renewal_mode": "spike",
                    "mobile_renewal_worker_url": "not-a-url",
                    "mobile_renewal_host_id": "host-1",
                    "mobile_renewal_shared_secret": "secret",
                }
            )
        self.assertIn("http(s)", str(ctx.exception))

    def test_safe_dict_masks_secret(self) -> None:
        from mobile_renewal_config import build_mobile_renewal_config, to_safe_dict

        cfg = build_mobile_renewal_config(
            {
                "mobile_renewal_mode": "spike",
                "mobile_renewal_worker_url": "https://example.com",
                "mobile_renewal_host_id": "host-1",
                "mobile_renewal_shared_secret": "secret",
            }
        )
        safe = to_safe_dict(cfg)
        self.assertEqual(safe["shared_secret"], "***")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class TestWorkerClient(unittest.TestCase):
    @patch("mobile_renewal_worker_client.requests.post")
    def test_create_renewal_request_ok(self, post) -> None:
        from mobile_renewal_worker_client import create_renewal_request

        post.return_value = _FakeResponse(
            {
                "ok": True,
                "request_id": "req_123",
                "action_url": "https://worker/r/tok",
                "expires_at": "2026-03-13T00:00:00Z",
            }
        )
        req = create_renewal_request(
            worker_url="https://worker",
            host_id="host-1",
            shared_secret="secret",
            service_name="svc",
            auth_status="expired",
            request_ttl_seconds=600,
            now=datetime(2026, 3, 13, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(req.request_id, "req_123")
        self.assertIn("/r/", req.action_url)

    @patch("mobile_renewal_worker_client.requests.post")
    def test_create_renewal_request_missing_fields(self, post) -> None:
        from mobile_renewal_worker_client import create_renewal_request

        post.return_value = _FakeResponse({"ok": True, "request_id": "req_123"})
        with self.assertRaises(ValueError):
            create_renewal_request(
                worker_url="https://worker",
                host_id="host-1",
                shared_secret="secret",
                service_name="svc",
                auth_status="expired",
                request_ttl_seconds=600,
                now=datetime(2026, 3, 13, 0, 0, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()

