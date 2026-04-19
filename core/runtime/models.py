"""Runtime-domain model exports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.execution_policy.models import ExecutionMode
from core.runtime.runtime_events import RuntimeEventPlane, RuntimeEventRecord
from core.runtime.runtime_process import RuntimeProcessRecord, RuntimeProcessStatus
from core.runtime.runtime_session import RuntimeSessionRecord, RuntimeSessionStatus
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_turns import RuntimeTurnRecord, RuntimeTurnStatus


__all__ = [
    "RuntimeEventPlane",
    "RuntimeEventRecord",
    "RuntimeLocation",
    "RuntimeProcessRecord",
    "RuntimeProcessStatus",
    "RuntimeRoutingDecision",
    "RuntimeSessionRecord",
    "RuntimeSessionStatus",
    "RuntimeStateRecord",
    "RuntimeTurnRecord",
    "RuntimeTurnStatus",
]


@dataclass(frozen=True)
class RuntimeLocation:
    """Describe the runtime root for one workspace."""

    workspace_id: str
    path: Path


@dataclass(frozen=True)
class RuntimeRoutingDecision:
    """Resolved runtime routing and filesystem boundary for one session."""

    workspace_id: str
    agent_id: str
    requested_mode: ExecutionMode | None
    effective_mode: ExecutionMode
    workspace_root: str
    workdir: str
    runtime_root: str
    writable_roots: list[str]
    allows_outside_workspace_root: bool
