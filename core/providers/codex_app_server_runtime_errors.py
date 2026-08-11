"""Typed Codex app-server transport failures."""

from __future__ import annotations


class CodexAppServerRequestError(RuntimeError):
    """Structured JSON-RPC rejection returned by Codex app-server."""

    def __init__(self, method: str, *, code: int | None, message: str, data: object = None) -> None:
        super().__init__(f"`{method}` failed against Codex app-server: {message}")
        self.method = method
        self.code = code
        self.message = message
        self.data = data


class CodexAppServerDeliveryUncertainError(RuntimeError):
    """A request may have reached Codex but its acknowledgement was not observed."""
