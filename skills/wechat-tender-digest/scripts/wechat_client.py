#!/usr/bin/env python3
"""Direct WeChat MP API client, replacing gateway_client.py.

Calls mp.weixin.qq.com directly using auth cookies/token from wechat_auth.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from wechat_auth import AuthState


MP_BASE = "https://mp.weixin.qq.com"
SEARCH_BIZ = f"{MP_BASE}/cgi-bin/searchbiz"
LIST_ARTICLES = f"{MP_BASE}/cgi-bin/appmsg"

REQUEST_INTERVAL = 1.5
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# WeChat articles sometimes return a security verify page to desktop user-agents.
# Using a WeChat Mobile (MicroMessenger) UA significantly reduces that risk.
ARTICLE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "MicroMessenger/8.0.49(0x1800312e) NetType/WIFI Language/zh_CN"
)

VERIFY_MARKERS = (
    "mmbizwap:secitptpage/verify.html",
    "secitptpage/verify",
)


@dataclass(frozen=True)
class WeChatError(Exception):
    event: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class AccountRef:
    fakeid: str
    name: str


class WeChatClient:
    """Direct WeChat MP API client using auth cookies/token."""

    def __init__(self, auth_state: AuthState):
        self.auth_state = auth_state
        self.token = auth_state.token
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Referer": f"{MP_BASE}/",
        })
        # Restore cookies from auth state
        for name, value in auth_state.cookies.items():
            self.session.cookies.set(name, value)
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        """Enforce minimum interval between requests to avoid rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        self._throttle()
        last_error: Optional[Exception] = None
        timeout = kwargs.pop("timeout", 30)
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.request(method, url, timeout=timeout, **kwargs)
                return response
            except requests.RequestException as error:
                last_error = error
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    time.sleep(delay)
        raise WeChatError("fetch_failed", f"请求 {url} 失败，已重试 {MAX_RETRIES} 次: {last_error}")

    def health(self) -> dict:
        """Verify auth token validity by making a lightweight request."""
        try:
            response = self._request_with_retry(
                "GET",
                SEARCH_BIZ,
                params={
                    "action": "search_biz",
                    "token": self.token,
                    "lang": "zh_CN",
                    "f": "json",
                    "ajax": 1,
                    "query": "test",
                    "begin": 0,
                    "count": 1,
                },
                timeout=15,
            )
            data = response.json()
            if data.get("base_resp", {}).get("ret") == 200013:
                return {"authStatus": "expired"}
            if data.get("base_resp", {}).get("ret") == 0:
                return {"authStatus": "healthy"}
            return {"authStatus": "unknown", "ret": data.get("base_resp", {}).get("ret")}
        except (requests.RequestException, WeChatError):
            return {"authStatus": "unreachable"}

    def resolve_accounts(self, accounts: tuple[str, ...]) -> list[AccountRef]:
        return [self.resolve_account(account) for account in accounts]

    def resolve_account(self, account: str) -> AccountRef:
        """Resolve account name to fakeid via search API."""
        if looks_like_fakeid(account):
            return AccountRef(fakeid=account, name=account)

        response = self._request_with_retry(
            "GET",
            SEARCH_BIZ,
            params={
                "action": "search_biz",
                "token": self.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
                "query": account,
                "begin": 0,
                "count": 5,
            },
            timeout=30,
        )
        data = response.json()
        base_ret = data.get("base_resp", {}).get("ret", -1)
        if base_ret == 200013:
            raise WeChatError("auth_expired", "登录已过期，请运行 --login 重新扫码")
        if base_ret != 0:
            raise WeChatError("fetch_failed", f"搜索公众号失败: ret={base_ret}")

        biz_list = data.get("list", [])
        if not biz_list:
            raise WeChatError("fetch_failed", f"未找到公众号: {account}")

        # Find exact match first, then use first result
        for biz in biz_list:
            nickname = biz.get("nickname", "")
            if nickname == account:
                return AccountRef(fakeid=str(biz["fakeid"]), name=nickname)

        # Use first result with warning
        first = biz_list[0]
        return AccountRef(fakeid=str(first["fakeid"]), name=str(first.get("nickname") or account))

    def _fetch_article_list_page(self, account: AccountRef, *, begin: int, count: int) -> dict:
        response = self._request_with_retry(
            "GET",
            LIST_ARTICLES,
            params={
                "action": "list_ex",
                "token": self.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
                "fakeid": account.fakeid,
                "type": 9,
                "query": "",
                "begin": begin,
                "count": count,
            },
            timeout=45,
        )
        data = response.json()
        base_ret = data.get("base_resp", {}).get("ret", -1)
        if base_ret == 200013:
            raise WeChatError("auth_expired", "登录已过期，请运行 --login 重新扫码")
        if base_ret != 0:
            raise WeChatError("fetch_failed", f"获取文章列表失败: ret={base_ret}")
        return data

    @staticmethod
    def _date_filter_decision(create_time: str, *, from_date: str, to_date: str) -> str:
        if not create_time:
            return "include"
        try:
            article_date = datetime.fromtimestamp(int(create_time)).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return "include"
        if article_date < from_date:
            return "stop"
        if article_date > to_date:
            return "skip"
        return "include"

    def list_articles(self, account: AccountRef, from_date: str, to_date: str) -> list[dict]:
        """List articles from an account within date range, handling pagination."""
        all_articles: list[dict] = []
        begin = 0
        count = 5

        while True:
            data = self._fetch_article_list_page(account, begin=begin, count=count)
            app_msg_list = data.get("app_msg_list", [])
            if not app_msg_list:
                break

            for item in app_msg_list:
                create_time = str(item.get("create_time", ""))
                decision = self._date_filter_decision(create_time, from_date=from_date, to_date=to_date)
                if decision == "stop":
                    return all_articles
                if decision == "skip":
                    continue
                all_articles.append({"title": item.get("title", ""), "url": item.get("link", ""), "create_time": create_time})

            # Check if there are more pages
            total = data.get("app_msg_cnt", 0)
            begin += count
            if begin >= total or len(app_msg_list) < count:
                break

        return all_articles

    def download_article_html(self, url: str) -> str:
        """Download article HTML content directly from public URL."""
        if not url:
            raise WeChatError("fetch_failed", "文章 URL 为空")
        response = self._request_with_retry(
            "GET",
            url,
            headers={
                **self.session.headers,
                "User-Agent": ARTICLE_USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=60,
        )
        if response.status_code != 200:
            raise WeChatError("fetch_failed", f"下载文章失败: HTTP {response.status_code}")
        html = response.text
        if _looks_like_verify_page(html):
            raise WeChatError(
                "fetch_failed",
                "下载文章触发微信安全验证页（verify.html），正文无法获取。"
                "建议：稍后重试，或切换网络/降低请求频率。",
            )
        return html


def looks_like_fakeid(value: str) -> bool:
    text = value.strip()
    return "=" in text or text.startswith(("Mz", "Mj"))


def _looks_like_verify_page(html: str) -> bool:
    text = html or ""
    return any(marker in text for marker in VERIFY_MARKERS)
