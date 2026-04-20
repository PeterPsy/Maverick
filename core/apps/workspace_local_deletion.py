"""Complete deletion for workspace-local app projects."""

from __future__ import annotations

from pathlib import Path
import shutil

from core.apps.errors import AppLifecycleError, WorkspaceAppBindingNotFoundError
from core.apps.paths import workspace_apps_root
from core.apps.status import purge_workspace_app_data
from core.apps.store import AppStore
from core.observability.service import record_platform_audit, record_platform_event


def delete_workspace_local_app_project(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
    observability_store=None,
) -> dict[str, object]:
    """Delete one workspace-local app project, its binding, and its workspace-owned data."""
    project = store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
    project_root = _safe_workspace_project_root(project.project_root, workspace_id=workspace_id, start_path=start_path)
    try:
        store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    except WorkspaceAppBindingNotFoundError:
        binding_removed = False
    else:
        store.delete_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
        binding_removed = True
    data_root = purge_workspace_app_data(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    if project_root.exists():
        shutil.rmtree(project_root)
    store.delete_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
    payload = {
        "workspace_id": workspace_id,
        "app_id": app_id,
        "project_id": project.project_id,
        "project_root": str(project_root),
        "data_root": str(data_root),
        "binding_removed": binding_removed,
        "project_removed": True,
        "data_removed": True,
    }
    if observability_store is not None:
        record_platform_audit(
            observability_store,
            action="app.workspace_local.delete",
            status="succeeded",
            source_domain="apps",
            detail=f"Deleted workspace-local app `{app_id}` from workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            app_id=app_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="app.workspace_local.deleted",
            event_plane="workspace",
            source_domain="apps",
            workspace_id=workspace_id,
            app_id=app_id,
            payload=payload,
        )
    return payload


def _safe_workspace_project_root(project_root: str, *, workspace_id: str, start_path: Path | None) -> Path:
    root = Path(project_root).expanduser().resolve(strict=False)
    allowed_root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path).resolve(strict=False)
    try:
        root.relative_to(allowed_root)
    except ValueError as error:
        raise AppLifecycleError(
            f"Workspace-local app project root `{root}` is outside workspace `{workspace_id}` apps root."
        ) from error
    if root == allowed_root:
        raise AppLifecycleError("Refusing to delete the workspace apps root.")
    return root
