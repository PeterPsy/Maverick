"""Discovery for workspace-local app projects on disk."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.apps.contract_records import APP_CONTRACT_FILENAME
from core.apps.registration import register_workspace_local_app_project_from_contract
from core.apps.store import AppStore
from core.apps.paths import workspace_apps_root


def sync_workspace_local_app_projects(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Register valid workspace-local app projects found under the workspace apps root."""
    root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path)
    if not root.is_dir():
        return []
    synced_app_ids: list[str] = []
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
        except Exception:
            continue
        synced_app_ids.append(record.app_id)
    return synced_app_ids
