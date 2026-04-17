"""Execution-policy models for effective workspace runtime enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ExecutionMode = Literal["sandbox", "full-access"]


@dataclass(frozen=True)
class WorkspaceExecutionProfile:
    """Effective execution profile for one workspace."""

    workspace_id: str
    requested_mode: ExecutionMode | None
    effective_mode: ExecutionMode
    default_can_use_full_access: bool
    governance_allows_full_access: bool
    platform_allows_full_access: bool
    sandbox_only: bool
    reason: str


@dataclass(frozen=True)
class WorkspaceRuntimeBoundary:
    """Filesystem boundary enforced for one workspace runtime."""

    workspace_id: str
    workspace_root: str
    writable_roots: list[str]
    allows_outside_workspace_root: bool
