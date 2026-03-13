#!/usr/bin/env python3
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Tuple

import requests

from wechat_auth import (
    LOGIN_CONFIRM,
    LOGIN_START,
    MP_BASE,
    QR_ASK_URL,
    QR_CODE_URL,
    AuthState,
    LoginError,
    TOKEN_LIFETIME_DAYS,
    USER_AGENT,
)


DEFAULT_HTTP_TIMEOUT_SECONDS = 15
DEFAULT_POLL_INTERVAL_SECONDS = 2


class WeChatLoginTimeout(LoginError):
    pass


class WeChatLoginCancelled(LoginError):
    pass


@dataclass(frozen=True)
class PreparedQrLogin:
    session: requests.Session
    qr_png_bytes: bytes


def begin_qr_login(*, timeout_seconds: int = DEFAULT_HTTP_TIMEOUT_SECONDS) -> PreparedQrLogin:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Referer": f"{MP_BASE}/", "Origin": MP_BASE})

    sid = str(int(time.time() * 1000))
    resp = session.post(
        LOGIN_START,
        data={
            "userlang": "zh_CN",
            "redirect_url": "",
            "login_type": "3",
            "sessionid": sid,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        },
        timeout=timeout_seconds,
    )
    resp.raise_for_status()

    qr_resp = session.get(f"{QR_CODE_URL}&random={int(time.time() * 1000)}", timeout=timeout_seconds)
    if int(qr_resp.status_code) != 200 or not qr_resp.content:
        raise LoginError(f"获取二维码失败: HTTP {qr_resp.status_code}")
    return PreparedQrLogin(session=session, qr_png_bytes=bytes(qr_resp.content))


def wait_for_login_token(
    session: requests.Session,
    *,
    timeout_seconds: int,
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    now: Callable[[], datetime] = datetime.now,
) -> str:
    deadline = now().timestamp() + float(timeout_seconds)
    while now().timestamp() < deadline:
        resp = session.get(
            QR_ASK_URL,
            params={"token": "", "lang": "zh_CN", "f": "json", "ajax": "1"},
            timeout=10,
        )
        data = resp.json()
        status = data.get("status")
        if status == 1:
            return _complete_login(session, timeout_seconds=DEFAULT_HTTP_TIMEOUT_SECONDS)
        if status in (2, 3):
            raise WeChatLoginCancelled("二维码已过期或登录已取消")
        time.sleep(float(poll_interval_seconds))
    raise WeChatLoginTimeout(f"扫码超时（{int(timeout_seconds)}秒），请重试")


def build_auth_state(*, session: requests.Session, token: str, now: Callable[[], datetime] = datetime.now) -> AuthState:
    current = now()
    return AuthState(
        cookies={k: v for k, v in session.cookies.items()},
        token=token,
        login_time=current.isoformat(),
        expires_at=(current + timedelta(days=TOKEN_LIFETIME_DAYS)).isoformat(),
    )


def _complete_login(session: requests.Session, *, timeout_seconds: int) -> str:
    resp = session.post(
        LOGIN_CONFIRM,
        data={
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": "0",
            "cookie_cleaned": "0",
            "plugin_used": "0",
            "login_type": "3",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        },
        timeout=timeout_seconds,
    )
    data = resp.json()
    redirect_url = str(data.get("redirect_url", ""))
    if "token=" in redirect_url:
        token = redirect_url.split("token=")[-1].split("&")[0]
        if token:
            return token
    token = str(data.get("token", "")).strip()
    if token:
        return token
    raise LoginError(f"登录失败，无法获取 token: {data}")

