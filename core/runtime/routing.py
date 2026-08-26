"""Workspace-aware runtime routing helpers."""

from __future__ import annotations

from pathlib import Path

from core.execution_policy.models import ExecutionMode
from core.execution_policy.service import resolve_workspace_execution_profile
from core.execution_policy.service import resolve_workspace_runtime_boundary
from core.runtime.models import RuntimeLocation, RuntimeRoutingDecision
from core.runtime.paths import runtime_session_root
from core.runtime.store import runtime_location
from core.workspaces.models import WorkspaceGovernanceRecord
from core.workspaces.paths import workspace_root


def resolve_runtime(workspace_id: str, start_path: Path | None = None) -> RuntimeLocation:
    """Resolve the runtime root for one workspace through the runtime service layer."""
    return runtime_location(workspace_id=workspace_id, start_path=start_path)


def resolve_runtime_execution_mode(
    *,
    workspace_id: str,
    requested_mode: str | None = None,
    governance: WorkspaceGovernanceRecord | None = None,
    platform_allows_full_access: bool = False,
) -> ExecutionMode:
    """Resolve the effective mode without materializing runtime filesystem paths."""
    return resolve_workspace_execution_profile(
        workspace_id=workspace_id,
        requested_mode=requested_mode,
        governance=governance,
        platform_allows_full_access=platform_allows_full_access,
    ).effective_mode


def build_runtime_routing(
    *,
    session_id: str | None = None,
    workspace_id: str,
    agent_id: str,
    requested_mode: str | None = None,
    governance: WorkspaceGovernanceRecord | None = None,
    platform_allows_full_access: bool = False,
    start_path: Path | None = None,
) -> RuntimeRoutingDecision:
    """Resolve the authoritative runtime routing boundary for one agent runtime."""
    boundary = resolve_workspace_runtime_boundary(
        workspace_id,
        requested_mode=requested_mode,
        governance=governance,
        platform_allows_full_access=platform_allows_full_access,
        start_path=start_path,
    )
    workspace_runtime = resolve_runtime(workspace_id=workspace_id, start_path=start_path).path
    runtime_root = (
        runtime_session_root(workspace_id=workspace_id, session_id=session_id, start_path=start_path)
        if session_id
        else workspace_runtime / "sessions" / agent_id
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    resolved_workspace_root = workspace_root(workspace_id=workspace_id, start_path=start_path)
    resolved_workspace_root.mkdir(parents=True, exist_ok=True)
    return RuntimeRoutingDecision(
        workspace_id=workspace_id,
        agent_id=agent_id,
        requested_mode=requested_mode if requested_mode in {"sandbox", "full-access"} else None,
        effective_mode="full-access" if boundary.allows_outside_workspace_root else "sandbox",
        workspace_root=str(resolved_workspace_root),
        workdir=str(resolved_workspace_root),
        runtime_root=str(runtime_root),
        readable_roots=boundary.readable_roots,
        writable_roots=boundary.writable_roots,
        allows_outside_workspace_root=boundary.allows_outside_workspace_root,
    )
