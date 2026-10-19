class Refusal(Exception):
    """A request the CLI will not process. Printed as {"error": reason, **detail}; exits with code."""

    def __init__(self, reason="INVALID_REQUEST", code=2, detail=None):
        self.reason = reason
        self.code = code
        self.detail = detail or {}
        super().__init__(reason)


def require(condition):
    """Refuse the request (INVALID_REQUEST, exit 2) unless condition holds."""
    if not condition:
        raise Refusal()
