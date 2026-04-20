"""Canonical path helpers for workspace runtime roots."""

from __future__ import annotations

from pathlib import Path

from core.workspaces.paths import workspace_paths


def workspace_runtime_root(workspace_id: str, start_path: Path | None = None) -> Path:
    """Return the runtime root for one workspace."""
    return workspace_paths(workspace_id=workspace_id, start_path=start_path).runtime


def runtime_session_root(workspace_id: str, session_id: str, start_path: Path | None = None) -> Path:
    """Return the provider/runtime state root for one runtime session."""
    return workspace_runtime_root(workspace_id=workspace_id, start_path=start_path) / "sessions" / session_id
