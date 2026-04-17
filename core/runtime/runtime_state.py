"""Mutable runtime state snapshot records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.runtime.runtime_session import RuntimeSessionStatus
from core.runtime.runtime_turns import RuntimeTurnStatus


@dataclass(frozen=True)
class RuntimeStateRecord:
    """Mutable execution snapshot for one runtime session."""

    session_id: str
    workspace_id: str
    current_turn_id: str | None
    session_status: RuntimeSessionStatus
    turn_status: RuntimeTurnStatus | None
    last_progress_at: datetime | None
    watchdog_deadline_at: datetime | None
    forced_stop_reason: str | None
    last_error_detail: str | None
    updated_at: datetime
