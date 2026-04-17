"""Execution-policy services."""

from __future__ import annotations

from pathlib import Path

from core.execution_policy.errors import UnsupportedExecutionModeError
from core.execution_policy.models import ExecutionMode, WorkspaceExecutionProfile, WorkspaceRuntimeBoundary
from core.workspaces.models import WorkspaceGovernanceRecord
from core.workspaces.paths import workspace_root


def normalize_requested_mode(requested_mode: str | None) -> ExecutionMode | None:
    """Normalize the requested execution mode."""
    if requested_mode is None:
        return None
    normalized = str(requested_mode).strip().lower()
    if normalized in {"sandbox", "full-access"}:
        return normalized
    raise UnsupportedExecutionModeError(f"Unsupported execution mode `{requested_mode}`.")


def resolve_workspace_execution_profile(
    workspace_id: str,
    requested_mode: str | None = None,
    *,
    governance: WorkspaceGovernanceRecord | None = None,
    platform_allows_full_access: bool = False,
) -> WorkspaceExecutionProfile:
    """Resolve the effective execution profile for one workspace."""
    normalized_requested_mode = normalize_requested_mode(requested_mode)
    default_workspace = workspace_id == "default"
    governance_allows_full_access = bool(governance and governance.allow_full_access_runtime)
    can_run_full_access = default_workspace and governance_allows_full_access and platform_allows_full_access
    if can_run_full_access and normalized_requested_mode == "full-access":
        effective_mode = "full-access"
        reason = "default workspace explicitly requested full-access and platform policy allows it"
    else:
        effective_mode = "sandbox"
        if not default_workspace:
            reason = "non-default workspaces are sandbox-only"
        elif normalized_requested_mode == "full-access" and not governance_allows_full_access:
            reason = "default workspace requested full-access but governance does not allow it"
        elif normalized_requested_mode == "full-access" and not platform_allows_full_access:
            reason = "default workspace requested full-access but platform policy does not allow it"
        else:
            reason = "default workspace defaults to sandbox"
    return WorkspaceExecutionProfile(
        workspace_id=workspace_id,
        requested_mode=normalized_requested_mode,
        effective_mode=effective_mode,
        default_can_use_full_access=default_workspace,
        governance_allows_full_access=governance_allows_full_access,
        platform_allows_full_access=platform_allows_full_access,
        sandbox_only=not default_workspace,
        reason=reason,
    )


def resolve_workspace_runtime_boundary(
    workspace_id: str,
    requested_mode: str | None = None,
    *,
    governance: WorkspaceGovernanceRecord | None = None,
    platform_allows_full_access: bool = False,
    start_path: Path | None = None,
) -> WorkspaceRuntimeBoundary:
    """Resolve the runtime filesystem boundary for one workspace."""
    profile = resolve_workspace_execution_profile(
        workspace_id=workspace_id,
        requested_mode=requested_mode,
        governance=governance,
        platform_allows_full_access=platform_allows_full_access,
    )
    root = workspace_root(workspace_id=workspace_id, start_path=start_path or Path(__file__))
    if profile.effective_mode == "full-access":
        writable_roots = ["/"]
        allows_outside_workspace_root = True
    else:
        writable_roots = [str(root)]
        allows_outside_workspace_root = False
    return WorkspaceRuntimeBoundary(
        workspace_id=workspace_id,
        workspace_root=str(root),
        writable_roots=writable_roots,
        allows_outside_workspace_root=allows_outside_workspace_root,
    )
