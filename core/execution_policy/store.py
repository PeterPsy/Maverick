"""Execution-policy storage entrypoints."""

from __future__ import annotations

from core.execution_policy.models import WorkspaceExecutionProfile


def profile_is_sandbox_only(profile: WorkspaceExecutionProfile) -> bool:
    """Return whether the effective workspace profile is sandbox-only."""
    return profile.sandbox_only
