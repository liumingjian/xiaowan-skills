#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Protocol


AUTH_STATUS_KEY = "authStatus"

AUTH_HEALTHY = "healthy"
AUTH_EXPIRED = "expired"
AUTH_UNREACHABLE = "unreachable"

TOKEN_LIFETIME_HOURS = 4


class HealthClient(Protocol):
    def health(self) -> Dict[str, Any]:
        ...


ClientFactory = Callable[[Any], HealthClient]
LoginFlow = Callable[[], Any]


@dataclass(frozen=True)
class AuthManagerError(Exception):
    event: str
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return self.message


@dataclass(frozen=True)
class AuthCheckResult:
    state: Any
    health: Dict[str, Any]
    refreshed: bool


class AuthManager:
    def __init__(
        self,
        store: Any,
        *,
        login_flow: LoginFlow,
        client_factory: ClientFactory,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._store = store
        self._login_flow = login_flow
        self._client_factory = client_factory
        self._now = now

    def check_and_refresh(self) -> AuthCheckResult:
        state = self._store.load()
        if not getattr(state, "token", ""):
            state = self._login_and_store()
            health = self._health_check(state)
            return AuthCheckResult(state=state, health=health, refreshed=True)
        health = self._health_check(state)
        status = str(health.get(AUTH_STATUS_KEY, "unknown"))
        if status == AUTH_HEALTHY:
            return AuthCheckResult(state=state, health=health, refreshed=False)
        if status == AUTH_EXPIRED:
            state = self._login_and_store()
            health = self._health_check(state)
            return AuthCheckResult(state=state, health=health, refreshed=True)
        if status == AUTH_UNREACHABLE:
            raise AuthManagerError(event="auth_unreachable", message="无法连接到微信接口，请检查网络后重试")
        raise AuthManagerError(event="auth_unknown", message=f"认证状态未知: {health}")

    def _login_and_store(self) -> Any:
        state = self._login_flow()
        self._refresh_local_expiry(state)
        self._store.save(state)
        return state

    def _health_check(self, state: Any) -> Dict[str, Any]:
        client = self._client_factory(state)
        health = client.health()
        if health.get(AUTH_STATUS_KEY) == AUTH_HEALTHY:
            self._refresh_local_expiry(state)
            self._store.save(state)
        return health

    def _refresh_local_expiry(self, state: Any) -> None:
        expires_at = self._now() + timedelta(hours=TOKEN_LIFETIME_HOURS)
        if not hasattr(state, "expires_at"):
            raise AuthManagerError(event="auth_state_invalid", message="AuthState 缺少 expires_at 字段")
        state.expires_at = expires_at.isoformat()
