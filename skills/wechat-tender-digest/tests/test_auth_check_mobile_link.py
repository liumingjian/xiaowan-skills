from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime
from pathlib import Path


RUN_CHECK_PATH = (
    Path(__file__).resolve().parents[1].parent / "wechat-tender-auth" / "scripts" / "run_check.py"
)


def load_run_check_module():
    spec = importlib.util.spec_from_file_location("wechat_tender_auth_run_check_mobile", RUN_CHECK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load run_check.py from {RUN_CHECK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthCheckMobileLinkTests(unittest.TestCase):
    def test_spike_mode_uses_dynamic_action_url(self) -> None:
        module = load_run_check_module()
        payload = {}
        captured = {"action_url": None, "handle_hint": None, "sent": 0}

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

        class Sender:
            webhook_url = "https://example.com"
            mentioned_list = ()
            mentioned_mobile_list = ()

        class DynamicReq:
            request_id = "req_123"
            action_url = "https://worker.example/r/tok_abc"
            expires_at = "2026-03-13T00:10:00Z"

        def build_config(_prefs):
            raise AssertionError("static build_config should not be used in spike mode")

        def build_sender_config(_prefs):
            return Sender()

        def build_mobile_config(_prefs):
            class MobileCfg:
                mode = "spike"
                worker_url = "https://worker.example"
                host_id = "host-1"
                shared_secret = "secret"
                request_ttl_seconds = 600

            return MobileCfg()

        def is_spike_enabled_fn(cfg) -> bool:
            return getattr(cfg, "mode", "") == "spike"

        def create_req(**_kwargs):
            return DynamicReq()

        def build_content(**kwargs):
            captured["action_url"] = kwargs.get("action_url")
            captured["handle_hint"] = kwargs.get("handle_hint")
            return "content"

        def send_text(**_kwargs):
            captured["sent"] += 1

        module._handle_notification(
            payload=payload,
            service_name="svc",
            auth_status="expired",
            timestamp="2026-03-13T13:10:00",
            now=datetime(2026, 3, 13, 13, 10, 0),
            get_prefs=lambda: {
                "wechat_work_webhook": "https://example.com",
                "mobile_renewal_mode": "spike",
                "mobile_renewal_worker_url": "https://worker.example",
                "mobile_renewal_host_id": "host-1",
                "mobile_renewal_shared_secret": "secret",
            },
            build_policy=lambda _prefs: object(),
            evaluate=lambda **_kwargs: Decision(),
            build_config=build_config,
            build_sender_config=build_sender_config,
            validate_url=lambda _url: {"ok": True, "reason": "ok", "status_code": 200},
            build_content=build_content,
            send_text=send_text,
            build_mobile_config=build_mobile_config,
            is_spike_enabled_fn=is_spike_enabled_fn,
            create_renewal_request_fn=create_req,
        )

        self.assertTrue(payload["wechat_work_notified"])
        self.assertEqual(payload["action_url_source"]["mode"], "spike")
        self.assertEqual(payload["action_url_source"]["request_id"], "req_123")
        self.assertEqual(captured["action_url"], "https://worker.example/r/tok_abc")
        self.assertIsNotNone(captured["handle_hint"])
        self.assertEqual(captured["sent"], 1)


if __name__ == "__main__":
    unittest.main()
