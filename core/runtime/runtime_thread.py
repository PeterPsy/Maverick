"""Core-owned chat/runtime thread records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RuntimeThreadRecord:
    """Workspace-scoped conversation thread owned by the core runtime domain."""

    thread_id: str
    workspace_id: str
    runtime_session_id: str
    title: str
    agent_label: str
    agent_type_id: str
    agent_role_id: str
    source_app_id: str
    system_prompt: str
    project_id: str | None
    archived: bool
    availability: str
    created_at: datetime
    updated_at: datetime
