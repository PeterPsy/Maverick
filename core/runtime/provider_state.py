"""Mutable provider-private continuation metadata for runtime sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RuntimeProviderState:
    """Revisioned mutable provider state separated from the session binding."""

    session_id: str
    workspace_id: str
    runtime_engine_id: str
    model_provider_id: str
    continuation_id: str | None
    provider_thread_id: str | None
    provider_request_id: str | None
    provider_private_envelope: dict[str, object] | None
    revision: int
    turn_generation: str | None
    updated_at: datetime
