"""Shared helpers for app-hosting lifecycle modules."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.apps.data_state import write_app_data_state
from core.apps.contracts import utcnow
from core.apps.errors import (
    AppDataRootError,
    AppLifecycleError,
)
from core.apps.models import (
    AppDataStateRecord,
    AppHookContext,
    AppSourceKind,
)
from core.apps.paths import workspace_app_data_root
from core.workspaces.paths import workspace_paths

def _timestamp(now: datetime | None = None) -> str:
    return (now or utcnow()).isoformat()

def _ensure_workspace_app_data_root(*, workspace_id: str, app_id: str, start_path: Path | None = None) -> Path:
    data_root = workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    data_root.mkdir(parents=True, exist_ok=True)
    if not data_root.is_dir():
        raise AppDataRootError(f"App data root `{data_root}` could not be prepared.")
    return data_root

def _write_current_data_state(
    *,
    data_root: Path,
    app_id: str,
    app_version: str,
    data_schema_version: str,
    now: datetime | None = None,
) -> AppDataStateRecord:
    state = AppDataStateRecord(
        app_id=app_id,
        app_version=app_version,
        data_schema_version=data_schema_version,
        updated_at=_timestamp(now),
    )
    write_app_data_state(data_root, state)
    return state

def _build_workspace_hook_payload(
    *,
    workspace_id: str,
    app_id: str,
    data_root: Path,
    source_kind: AppSourceKind,
    source_record_id: str,
    hook_name: str,
    start_path: Path | None = None,
) -> dict[str, object]:
    workspace = workspace_paths(workspace_id=workspace_id, start_path=start_path)
    context = AppHookContext(
        workspace_id=workspace_id,
        workspace_root=str(workspace.root),
        export_root=str(workspace.root),
        app_id=app_id,
        data_root=str(data_root),
        uploaded_storage_root=str(workspace.uploaded_storage),
        generated_storage_root=str(workspace.generated_storage),
        source_kind=source_kind,
        source_record_id=source_record_id,
        hook_name=hook_name,
    )
    return context.__dict__

def _parse_version_tuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as error:
        raise AppLifecycleError(f"Unsupported app version `{version}` in reinstall flow.") from error
