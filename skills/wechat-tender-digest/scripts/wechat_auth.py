#!/usr/bin/env python3
"""WeChat MP QR code login and auth token persistence.

Replaces auth-gateway-daemon: handles QR login flow and stores
cookies/token in ~/.wechat-bid-digest/auth/state.json.
"""
from __future__ import annotations

import io
import json
import math
import os
import sys
import time
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import requests


AUTH_DIR = Path.home() / ".wechat-bid-digest" / "auth"
STATE_FILE = AUTH_DIR / "state.json"
MP_BASE = "https://mp.weixin.qq.com"
LOGIN_START = f"{MP_BASE}/cgi-bin/bizlogin?action=startlogin"
QR_CODE_URL = f"{MP_BASE}/cgi-bin/scanloginqrcode?action=getqrcode"
QR_ASK_URL = f"{MP_BASE}/cgi-bin/scanloginqrcode?action=ask"
LOGIN_CONFIRM = f"{MP_BASE}/cgi-bin/bizlogin?action=login"

POLL_INTERVAL = 2
POLL_TIMEOUT = 120
TOKEN_LIFETIME_DAYS = 4

QR_TERMINAL_CHAR_WIDTH_PER_PIXEL = 2
QR_TERMINAL_SIDE_PADDING_PIXELS = 2
QR_TERMINAL_MIN_PIXELS = 21
# Cap terminal QR width so it stays scannable without taking the whole screen.
QR_TERMINAL_MAX_PIXELS = 60
QR_TERMINAL_THRESHOLD = 128

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class LoginError(Exception):
    pass


@dataclass
class AuthState:
    cookies: dict[str, str] = field(default_factory=dict)
    token: str = ""
    login_time: str = ""
    expires_at: str = ""

    def is_valid(self) -> bool:
        if not self.token or not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.now() < expires
        except ValueError:
            return False


class AuthStore:
    """Read/write auth state to ~/.wechat-bid-digest/auth/state.json."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or STATE_FILE

    def load(self) -> AuthState:
        if not self.path.exists():
            return AuthState()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return AuthState(
                cookies=data.get("cookies", {}),
                token=data.get("token", ""),
                login_time=data.get("login_time", ""),
                expires_at=data.get("expires_at", ""),
            )
        except (json.JSONDecodeError, KeyError):
            return AuthState()

    def save(self, state: AuthState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Restrict permissions to owner only
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


def ensure_auth(store: AuthStore) -> AuthState:
    """Return a valid AuthState, triggering QR login if expired."""
    state = store.load()
    if state.is_valid():
        return state
    print("认证已过期或不存在，需要重新扫码登录...", file=sys.stderr)
    state = qr_login_flow()
    store.save(state)
    return state


def qr_login_flow() -> AuthState:
    """Execute full QR code login flow against WeChat MP."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": f"{MP_BASE}/",
        "Origin": MP_BASE,
    })

    # Step 1: Start login to get uuid cookie
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
        timeout=15,
    )
    resp.raise_for_status()

    # Step 2: Get QR code image
    qr_resp = session.get(f"{QR_CODE_URL}&random={int(time.time() * 1000)}", timeout=15)
    if qr_resp.status_code != 200:
        raise LoginError(f"获取二维码失败: HTTP {qr_resp.status_code}")

    # Display QR code
    _display_qr_code(qr_resp.content)

    # Step 3: Poll for scan result
    print("\n请使用微信扫描上方二维码...", file=sys.stderr)
    token = _poll_for_scan(session)

    now = datetime.now()
    return AuthState(
        cookies={k: v for k, v in session.cookies.items()},
        token=token,
        login_time=now.isoformat(),
        expires_at=(now + timedelta(days=TOKEN_LIFETIME_DAYS)).isoformat(),
    )


def _display_qr_code(image_data: bytes) -> None:
    """Display QR code in terminal; persist PNG only if terminal rendering is unavailable."""
    if not image_data:
        raise LoginError("二维码数据为空")
    try:
        _render_qr_to_terminal(image_data)
    except LoginError as error:
        qr_path = _save_qr_png(image_data)
        print(f"\n无法在控制台渲染二维码（{error}），已保存到: {qr_path}", file=sys.stderr)
    sys.stderr.flush()


def _render_qr_to_terminal(image_data: bytes) -> None:
    try:
        from PIL import Image
    except ImportError as error:
        raise LoginError("缺少 Pillow 依赖，无法在控制台显示二维码。请安装: pip install qrcode[pil]") from error

    terminal_width = shutil.get_terminal_size(fallback=(96, 24)).columns
    max_pixels = _compute_terminal_max_pixels(terminal_width)
    image = Image.open(io.BytesIO(image_data)).convert("L")
    scale = _compute_resize_scale(image.width, max_pixels)
    new_width = max(1, int(image.width // scale))
    new_height = max(1, int(image.height // scale))
    resized = image.resize((new_width, new_height), resample=Image.NEAREST)
    pixels = resized.load()
    assert pixels is not None

    threshold = QR_TERMINAL_THRESHOLD
    for y in range(resized.height):
        line = []
        for x in range(resized.width):
            line.append("██" if int(pixels[x, y]) < threshold else "  ")
        print("".join(line), file=sys.stderr)


def _compute_terminal_max_pixels(terminal_columns: int) -> int:
    """Compute max QR pixel width so the printed lines never wrap."""
    if int(terminal_columns) <= 0:
        raise LoginError("无法获取终端宽度，无法渲染二维码")
    max_by_terminal = (int(terminal_columns) // QR_TERMINAL_CHAR_WIDTH_PER_PIXEL) - QR_TERMINAL_SIDE_PADDING_PIXELS
    if max_by_terminal < QR_TERMINAL_MIN_PIXELS:
        min_cols = (QR_TERMINAL_MIN_PIXELS + QR_TERMINAL_SIDE_PADDING_PIXELS) * QR_TERMINAL_CHAR_WIDTH_PER_PIXEL
        raise LoginError(f"终端宽度不足（{terminal_columns}列），至少需要 {min_cols} 列才能显示二维码")
    return min(int(max_by_terminal), QR_TERMINAL_MAX_PIXELS)


def _compute_resize_scale(image_width: int, max_pixels: int) -> int:
    if int(image_width) <= 0:
        raise LoginError("二维码图片宽度异常")
    if int(max_pixels) <= 0:
        raise LoginError("二维码渲染宽度异常")
    # NOTE: must use ceil to guarantee resized width <= max_pixels, otherwise it may wrap and become unscannable.
    return max(1, int(math.ceil(float(image_width) / float(max_pixels))))


def _save_qr_png(image_data: bytes) -> Path:
    qr_path = AUTH_DIR / "qrcode.png"
    qr_path.parent.mkdir(parents=True, exist_ok=True)
    qr_path.write_bytes(image_data)
    return qr_path


def _poll_for_scan(session: requests.Session) -> str:
    """Poll WeChat MP for QR code scan status."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            resp = session.get(
                QR_ASK_URL,
                params={"token": "", "lang": "zh_CN", "f": "json", "ajax": "1"},
                timeout=10,
            )
            data = resp.json()
            status = data.get("status")

            if status == 1:
                # Confirmed — complete login
                return _complete_login(session)
            elif status in [4, 6]:
                # Scanned, waiting for confirm
                print("已扫码，请在手机上确认登录...", file=sys.stderr)
            elif status in [2, 3]:
                # Expired or cancelled
                raise LoginError("二维码已过期或登录已取消")
            elif status == 0:
                # Not scanned yet
                pass

        except requests.RequestException:
            pass

        time.sleep(POLL_INTERVAL)

    raise LoginError(f"扫码超时（{POLL_TIMEOUT}秒），请重试")


def _complete_login(session: requests.Session) -> str:
    """Complete login and extract token from redirect."""
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
        timeout=15,
    )
    data = resp.json()
    redirect_url = data.get("redirect_url", "")

    # Extract token from redirect URL
    if "token=" in redirect_url:
        token = redirect_url.split("token=")[-1].split("&")[0]
        if token:
            print("登录成功!", file=sys.stderr)
            return token

    # Try to get token from response
    token = str(data.get("token", ""))
    if token:
        print("登录成功!", file=sys.stderr)
        return token

    raise LoginError(f"登录失败，无法获取 token: {data}")
