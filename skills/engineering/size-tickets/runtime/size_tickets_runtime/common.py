class Refusal(Exception):
    """A request the CLI will not process. Printed as {"error": reason, **detail}; exits with code."""

    def __init__(self, reason="INVALID_REQUEST", code=2, detail=None):
        self.reason = reason
        self.code = code
        self.detail = detail or {}
        super().__init__(reason)
