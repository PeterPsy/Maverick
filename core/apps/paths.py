"""Canonical path helpers for platform apps and workspace app storage."""

from __future__ import annotations

from pathlib import Path

from core.shared.repository import installation_paths
from core.workspaces.paths import workspace_paths


def installed_apps_root(start_path: Path | None = None) -> Path:
    """Return the platform-level apps root."""
    return installation_paths(start_path=start_path).apps_root


def installed_app_root(app_id: str, start_path: Path | None = None) -> Path:
    """Return the source root for one platform-installed app."""
    return installed_apps_root(start_path=start_path) / app_id


def external_app_bundles_root(start_path: Path | None = None) -> Path:
    """Return the trusted installation-managed root for external app bundles."""
    return installed_apps_root(start_path=start_path) / "_bundles"


def workspace_apps_root(workspace_id: str, start_path: Path | None = None) -> Path:
    """Return the workspace-local app development root."""
    return workspace_paths(workspace_id=workspace_id, start_path=start_path).apps


def workspace_app_data_root(workspace_id: str, app_id: str, start_path: Path | None = None) -> Path:
    """Return the app-owned data root inside one workspace."""
    return workspace_paths(workspace_id=workspace_id, start_path=start_path).data / app_id
