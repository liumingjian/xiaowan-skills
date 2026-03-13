#!/usr/bin/env python3
from __future__ import annotations

import unittest

import support  # noqa: F401  # adds scripts/ to sys.path

from auth_check import check_auth_health


class AuthCheckTests(unittest.TestCase):
    def test_check_auth_health_without_token(self) -> None:
        class Store:
            def load(self):
                class State:
                    token = ""

                return State()

        health = check_auth_health(store=Store(), client_factory=lambda _s: None)  # type: ignore[arg-type,return-value]
        self.assertEqual(health.get("authStatus"), "expired")
        self.assertEqual(health.get("reason"), "not_logged_in")

    def test_check_auth_health_uses_client_factory(self) -> None:
        class Store:
            def load(self):
                class State:
                    token = "t"

                return State()

        class Client:
            def health(self):
                return {"authStatus": "healthy"}

        called = {"count": 0}

        def factory(_state):
            called["count"] += 1
            return Client()

        health = check_auth_health(store=Store(), client_factory=factory)  # type: ignore[arg-type]
        self.assertEqual(health.get("authStatus"), "healthy")
        self.assertEqual(called["count"], 1)


if __name__ == "__main__":
    unittest.main()

