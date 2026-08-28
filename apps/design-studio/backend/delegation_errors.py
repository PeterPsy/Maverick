"""Public errors returned by the Design Studio delegation surface."""

from __future__ import annotations


class DelegationError(RuntimeError):
    """A bounded public delegation failure."""

    def __init__(self, code: str, detail: str, *, status_code: int) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)
