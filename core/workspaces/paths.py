"""Canonical path helpers for workspace roots and workspace-owned storage."""

from __future__ import annotations

import re

from pathlib import Path

from core.shared.repository import installation_paths
from core.workspaces.errors import InvalidWorkspaceIdError
from core.workspaces.models import WorkspacePaths


WORKSPACE_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")


def validate_workspace_id(workspace_id: str) -> str:
    """Validate a workspace identifier against the v3 filesystem contract."""
    if not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise InvalidWorkspaceIdError(
            "Workspace IDs must be 2-64 chars, lowercase alphanumeric, and may contain '-' or '_' internally."
        )
    return workspace_id


def workspace_root(workspace_id: str, start_path: Path | None = None) -> Path:
    """Return the root directory for one workspace."""
    valid_workspace_id = validate_workspace_id(workspace_id)
    return installation_paths(start_path=start_path).workspaces_root / valid_workspace_id


def workspace_paths(workspace_id: str, start_path: Path | None = None) -> WorkspacePaths:
    """Return the canonical path set for one workspace."""
    root = workspace_root(workspace_id=workspace_id, start_path=start_path)
    storage = root / "storage"
    return WorkspacePaths(
        workspace_id=workspace_id,
        root=root,
        apps=root / "apps",
        data=root / "data",
        logs=root / "logs",
        runtime=root / "runtime",
        storage=storage,
        uploaded_storage=storage / "uploaded",
        generated_storage=storage / "generated",
        tests=root / "tests",
        tmp=root / "tmp",
    )

