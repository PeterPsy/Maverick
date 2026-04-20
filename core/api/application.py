"""Application bootstrap for the Maverick v3 core."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.apps.builtin_apps import register_and_install_builtin_apps_for_active_workspaces
from core.apps.store import AppStore
from core.providers.service import register_builtin_providers
from core.providers.store import ProviderStore
from core.shared.repository import installation_paths
from core.workspaces.service import ensure_default_workspace, ensure_default_workspace_record
from core.workspaces.store import WorkspaceStore


def create_application(
    *,
    start_path: Path | None = None,
    workspace_store: WorkspaceStore | None = None,
    app_store: AppStore | None = None,
    provider_store: ProviderStore | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    """Bootstrap the installation layout and default workspace state."""
    paths = installation_paths(start_path=start_path or Path(__file__))
    paths.core_root.mkdir(parents=True, exist_ok=True)
    paths.apps_root.mkdir(parents=True, exist_ok=True)
    paths.workspaces_root.mkdir(parents=True, exist_ok=True)
    paths.platform_logs_root.mkdir(parents=True, exist_ok=True)
    paths.runtime_logs_root.mkdir(parents=True, exist_ok=True)
    ensure_default_workspace(start_path=paths.repository_root)
    if workspace_store is not None:
        ensure_default_workspace_record(workspace_store, now=now)
    builtin_app_count = 0
    if workspace_store is not None and app_store is not None:
        installed_by_workspace = register_and_install_builtin_apps_for_active_workspaces(
            app_store,
            workspace_store,
            start_path=paths.repository_root,
            now=now,
        )
        builtin_app_count = sum(len(app_ids) for app_ids in installed_by_workspace.values())
    if provider_store is not None:
        register_builtin_providers(provider_store)
    return {
        "name": "maverick-core",
        "status": "initialized",
        "repository_root": str(paths.repository_root),
        "default_workspace_id": "default",
        "core_skill_count": "0",
        "builtin_app_count": str(builtin_app_count),
    }
