#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Protocol

from wechat_auth import AuthState, AuthStore


AUTH_STATUS_KEY = "authStatus"


class HealthClient(Protocol):
    def health(self) -> Dict[str, Any]:
        ...


ClientFactory = Callable[[AuthState], HealthClient]
NowFn = Callable[[], datetime]


@dataclass(frozen=True)
class AuthCheckOutput:
    health: Dict[str, Any]
    timestamp: str


def check_auth_health(*, store: AuthStore, client_factory: ClientFactory) -> Dict[str, Any]:
    state = store.load()
    if not getattr(state, "token", ""):
        return {AUTH_STATUS_KEY: "expired", "reason": "not_logged_in"}
    client = client_factory(state)
    return client.health()


def build_auth_check_payload(*, service_name: str, health: Dict[str, Any], timestamp: str) -> Dict[str, Any]:
    return {
        "type": "status",
        "event": "auth_check_completed",
        "service": service_name,
        "auth": health,
        "timestamp": timestamp,
    }


def run_auth_check(*, service_name: str, store: AuthStore, client_factory: ClientFactory, now: NowFn) -> AuthCheckOutput:
    timestamp = now().isoformat()
    health = check_auth_health(store=store, client_factory=client_factory)
    return AuthCheckOutput(health=health, timestamp=timestamp)

