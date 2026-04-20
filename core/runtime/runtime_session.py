"""Runtime session records."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    workspace_root: str
    workdir: str
    runtime_root: str
    started_at: datetime | None
    updated_at: datetime
    ended_at: datetime | None
    last_progress_at: datetime | None
    system_prompt: str | None = None
    skill_ids: list[str] = field(default_factory=list)
    source_app_id: str | None = None
    provider_id: str | None = None
    provider_thread_id: str | None = None
