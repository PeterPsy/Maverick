"""Domain errors for Marta Ops."""

from __future__ import annotations


class MartaOpsError(ValueError):
    """Return a safe validation or not-found error to the mounted backend."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code
