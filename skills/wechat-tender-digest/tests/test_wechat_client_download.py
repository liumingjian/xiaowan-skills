#!/usr/bin/env python3
from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from support import SCRIPTS  # noqa: F401  # ensures scripts/ is on sys.path


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    text: str


VERIFY_HTML = "<script>var PAGE_MID='mmbizwap:secitptpage/verify.html';</script>"
NORMAL_HTML = "<html><div id=\"js_content\">ok</div></html>"


class WeChatClientDownloadTests(unittest.TestCase):
    def _make_client(self):
        from wechat_auth import AuthState
        from wechat_client import WeChatClient

        return WeChatClient(AuthState(cookies={}, token="t", login_time="", expires_at=""))

    def test_looks_like_verify_page(self) -> None:
        from wechat_client import _looks_like_verify_page

        self.assertTrue(_looks_like_verify_page(VERIFY_HTML))
        self.assertFalse(_looks_like_verify_page(NORMAL_HTML))

    def test_download_article_html_sets_mobile_user_agent(self) -> None:
        from wechat_client import ARTICLE_USER_AGENT

        client = self._make_client()

        def fake_request(method: str, url: str, **kwargs):
            headers = kwargs.get("headers") or {}
            self.assertEqual(headers.get("User-Agent"), ARTICLE_USER_AGENT)
            return FakeResponse(status_code=200, text=NORMAL_HTML)

        with patch.object(client, "_request_with_retry", side_effect=fake_request):
            html = client.download_article_html("https://example.com")
        self.assertIn("js_content", html)

    def test_download_article_html_raises_on_verify_page(self) -> None:
        from wechat_client import WeChatError

        client = self._make_client()
        with patch.object(client, "_request_with_retry", return_value=FakeResponse(status_code=200, text=VERIFY_HTML)):
            with self.assertRaises(WeChatError):
                client.download_article_html("https://example.com")

    def test_download_article_html_returns_html_on_success(self) -> None:
        client = self._make_client()
        with patch.object(client, "_request_with_retry", return_value=FakeResponse(status_code=200, text=NORMAL_HTML)):
            html = client.download_article_html("https://example.com")
        self.assertEqual(html, NORMAL_HTML)


if __name__ == "__main__":
    unittest.main()
