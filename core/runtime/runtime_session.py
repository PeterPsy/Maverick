"""Runtime session records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.execution_policy.models import ExecutionMode


RuntimeSessionStatus = Literal["created", "running", "stopping", "stopped", "failed"]


@dataclass(frozen=True)
class RuntimeSessionRecord:
    """Lifecycle container for one running runtime session."""

    session_id: str
    workspace_id: str
    agent_id: str
    status: RuntimeSessionStatus
    requested_mode: ExecutionMode | None
    effective_mode: ExecutionMode
    workdir: str
    runtime_root: str
    started_at: datetime | None
    updated_at: datetime
    ended_at: datetime | None
    last_progress_at: datetime | None
