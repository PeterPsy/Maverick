"""Browser app error types."""

from __future__ import annotations


class BrowserValidationError(ValueError):
    """Raised when a Browser app request is malformed."""

    def __init__(self, detail: str, *, field: str | None = None) -> None:
        super().__init__(detail)
        self.field = field


class BrowserPolicyError(PermissionError):
    """Raised when core egress or action policy denies a browser request."""

    def __init__(self, detail: str, *, decision: dict | None = None) -> None:
        super().__init__(detail)
        self.decision = decision or {}


class BrowserBrokerUnavailableError(RuntimeError):
    """Raised when a broker-backed browser action is requested before Passo 4."""
