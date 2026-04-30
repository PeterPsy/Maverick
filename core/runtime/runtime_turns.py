"""Runtime turn records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


RuntimeTurnStatus = Literal["queued", "active", "completed", "failed", "cancelled", "timed-out"]


@dataclass(frozen=True)
class RuntimeTurnRecord:
    """One execution turn inside a runtime session."""

    turn_id: str
    session_id: str
    workspace_id: str
    status: RuntimeTurnStatus
    input_text: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
