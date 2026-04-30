"""Authorization-domain errors."""

from __future__ import annotations


class AuthorizationError(PermissionError):
    """Raised when an actor is not allowed to perform a platform action."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
