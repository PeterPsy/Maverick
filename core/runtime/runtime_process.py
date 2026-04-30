"""Runtime process records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


RuntimeProcessStatus = Literal["created", "running", "exited", "failed", "terminated", "timed-out"]


@dataclass(frozen=True)
class RuntimeProcessRecord:
    """Execution-handle metadata for one local runtime process."""

    process_id: str
    session_id: str
    workspace_id: str
    status: RuntimeProcessStatus
    command: list[str]
    cwd: str
    stdin_open: bool
    stdout_open: bool
    exit_code: int | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    failure_reason: str | None
