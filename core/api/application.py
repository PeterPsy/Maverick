"""Application bootstrap for the Maverick v3 core."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.shared.repository import installation_paths
from core.workspaces.service import ensure_default_workspace, ensure_default_workspace_record
from core.workspaces.store import WorkspaceStore


def create_application(
    *,
    start_path: Path | None = None,
    workspace_store: WorkspaceStore | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    """Bootstrap the installation layout and default workspace state."""
    paths = installation_paths(start_path=start_path or Path(__file__))
    paths.core_root.mkdir(parents=True, exist_ok=True)
    paths.apps_root.mkdir(parents=True, exist_ok=True)
    paths.workspaces_root.mkdir(parents=True, exist_ok=True)
    ensure_default_workspace(start_path=paths.repository_root)
    if workspace_store is not None:
        ensure_default_workspace_record(workspace_store, now=now)
    return {
        "name": "maverick-core",
        "status": "initialized",
        "repository_root": str(paths.repository_root),
        "default_workspace_id": "default",
    }
