"""Structured runtime event records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


RuntimeEventPlane = Literal["session", "turn", "process", "runtime"]


@dataclass(frozen=True)
class RuntimeEventRecord:
    """Structured runtime-domain event emitted during one session lifecycle."""

    event_id: str
    workspace_id: str
    session_id: str
    plane: RuntimeEventPlane
    event_type: str
    turn_id: str | None
    process_id: str | None
    payload: dict[str, Any]
    created_at: datetime
