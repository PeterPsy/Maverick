"""Domain contracts for Core-owned encrypted runtime payloads."""

from __future__ import annotations

from dataclasses import dataclass


PRIVATE_PAYLOAD_ENCRYPTION_PROFILE = "aes-256-gcm-v1"


@dataclass(frozen=True)
class RuntimePrivatePayloadContext:
    """Identity fields integrity-bound to one encrypted private payload."""

    namespace: str
    workspace_id: str
    session_id: str
    binding_fields: tuple[tuple[str, str], ...]


class RuntimePrivatePayloadError(RuntimeError):
    """Private-store failure with a stable, content-free reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
