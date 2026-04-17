"""Workspace bootstrap services."""

from __future__ import annotations

from pathlib import Path

from core.workspaces.models import WorkspacePaths
from core.workspaces.paths import workspace_paths


def ensure_workspace_layout(workspace_id: str, start_path: Path | None = None) -> WorkspacePaths:
    """Create the canonical directory layout for one workspace if it does not exist."""
    paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
    directories = (
        paths.root,
        paths.apps,
        paths.data,
        paths.logs,
        paths.runtime,
        paths.storage,
        paths.uploaded_storage,
        paths.generated_storage,
        paths.tests,
        paths.tmp,
    )
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def ensure_default_workspace(start_path: Path | None = None) -> WorkspacePaths:
    """Create the default workspace root using the canonical layout."""
    return ensure_workspace_layout(workspace_id="default", start_path=start_path)

