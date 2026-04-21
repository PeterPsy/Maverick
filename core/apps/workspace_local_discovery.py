"""Discovery for workspace-local app projects on disk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.apps.errors import AppHostingError
from core.apps.contract_records import APP_CONTRACT_FILENAME
from core.apps.registration import register_workspace_local_app_project_from_contract
from core.apps.store import AppStore
from core.apps.paths import workspace_apps_root


@dataclass(frozen=True)
class InvalidWorkspaceLocalAppProject:
    """Describe one workspace-local app project that exists but cannot be registered."""

    app_id: str
    project_root: str
    error: str


@dataclass(frozen=True)
class WorkspaceLocalAppDiscoveryResult:
    """Result of scanning workspace-local app projects on disk."""

    synced_app_ids: list[str]
    invalid_projects: list[InvalidWorkspaceLocalAppProject]


def discover_workspace_local_app_projects(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
    now: datetime | None = None,
) -> WorkspaceLocalAppDiscoveryResult:
    """Register valid workspace-local app projects and report invalid projects."""
    root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path)
    if not root.is_dir():
        return WorkspaceLocalAppDiscoveryResult(synced_app_ids=[], invalid_projects=[])
    synced_app_ids: list[str] = []
    invalid_projects: list[InvalidWorkspaceLocalAppProject] = []
    for project_root in sorted(path for path in root.iterdir() if path.is_dir()):
        if not (project_root / APP_CONTRACT_FILENAME).is_file():
            continue
        try:
            record = register_workspace_local_app_project_from_contract(
                store,
                workspace_id=workspace_id,
                project_root=str(project_root),
                now=now,
            )
        except AppHostingError as error:
            invalid_projects.append(
                InvalidWorkspaceLocalAppProject(
                    app_id=project_root.name,
                    project_root=str(project_root),
                    error=str(error),
                )
            )
            continue
        synced_app_ids.append(record.app_id)
    return WorkspaceLocalAppDiscoveryResult(synced_app_ids=synced_app_ids, invalid_projects=invalid_projects)


def sync_workspace_local_app_projects(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Register valid workspace-local app projects found under the workspace apps root."""
    return discover_workspace_local_app_projects(
        store,
        workspace_id=workspace_id,
        start_path=start_path,
        now=now,
    ).synced_app_ids
