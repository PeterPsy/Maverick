"""App-hosting services for app installation and enablement."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import shutil
from uuid import uuid4

from core.apps.data_state import read_app_data_state, write_app_data_state
from core.apps.contracts import (
    build_app_compatibility,
    build_app_capabilities,
    build_app_contract,
    build_app_distribution,
    build_app_entrypoints,
    build_app_failure_semantics,
    build_app_health_contract,
    build_app_hook_timeouts,
    build_app_lifecycle,
    build_app_rollback_support,
    build_app_storage,
    _normalize_slug,
    parse_app_contract_file,
    parsed_contract_to_app_source_record,
    parsed_contract_to_workspace_local_project_record,
    utcnow,
    write_app_contract_file,
)
from core.apps.errors import (
    AppDataRootError,
    AppLifecycleError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.models import (
    AppDataStateRecord,
    AppHookContext,
    AppSourceKind,
    AppSourceRecord,
    ParsedAppContract,
    WorkspaceAppBindingRecord,
    WorkspaceAppReinstallResult,
    WorkspaceAppStatus,
    WorkspaceAppUpgradeResult,
    WorkspaceLocalAppProjectRecord,
)
from core.apps.paths import workspace_app_data_root
from core.apps.store import AppStore
from core.apps.lifecycle import (
    ensure_app_compatible,
    finalize_install_status,
    load_contract_from_source_record,
    load_contract_from_workspace_project,
    run_health_check,
    run_lifecycle_hook,
    run_reactivation_hooks,
)
from core.observability.service import record_platform_audit, record_platform_event
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
