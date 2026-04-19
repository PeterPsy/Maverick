"""App source and workspace-local project registration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.apps.contracts import (
    _normalize_slug,
    parse_app_contract_file,
    parsed_contract_to_app_source_record,
    parsed_contract_to_workspace_local_project_record,
)
from core.apps.errors import AppLifecycleError
from core.apps.models import (
    AppSourceKind,
    AppSourceRecord,
    WorkspaceAppBindingRecord,
    WorkspaceAppStatus,
    WorkspaceLocalAppProjectRecord,
)
from core.apps.store import AppStore

from core.apps.service_common import _timestamp

def build_workspace_app_binding_record(
    *,
    workspace_id: str,
    app_id: str,
    source_record_id: str,
    source_kind: AppSourceKind,
    status: WorkspaceAppStatus,
    active_version: str,
    data_root: str,
    binding_id: str | None = None,
    now: datetime | None = None,
) -> WorkspaceAppBindingRecord:
    """Build one workspace app binding record."""
    timestamp = _timestamp(now)
    normalized_app_id = _normalize_slug(app_id, fallback="app")
    return WorkspaceAppBindingRecord(
        binding_id=binding_id or f"{workspace_id}:{normalized_app_id}",
        workspace_id=workspace_id,
        app_id=normalized_app_id,
        source_record_id=source_record_id,
        source_kind=source_kind,
        status=status,
        active_version=active_version,
        data_root=data_root,
        installed_at=timestamp,
        updated_at=timestamp,
    )

def register_app_source(store: AppStore, record: AppSourceRecord) -> AppSourceRecord:
    """Persist one installation-level app source record."""
    return store.save_app_source(record)

def register_workspace_local_app_project(
    store: AppStore, record: WorkspaceLocalAppProjectRecord
) -> WorkspaceLocalAppProjectRecord:
    """Persist one workspace-local app project record."""
    return store.save_workspace_local_app_project(record)

def register_app_source_from_contract(
    store: AppStore,
    *,
    source_kind: AppSourceKind,
    source_path: str,
    source_id: str | None = None,
    now: datetime | None = None,
) -> AppSourceRecord:
    """Parse one canonical app contract file and persist an installation-level source record."""
    if source_kind not in {"platform", "external_bundle"}:
        raise AppLifecycleError(f"Unsupported installation-level app source kind `{source_kind}`.")
    parsed = parse_app_contract_file(Path(source_path))
    if parsed.contract.distribution.mode == "workspace_local":
        raise AppLifecycleError("Workspace-local app contracts cannot be registered as installation-level app sources.")
    record = parsed_contract_to_app_source_record(
        parsed=parsed,
        source_kind=source_kind,
        source_path=source_path,
        source_id=source_id,
        now=now,
    )
    return register_app_source(store, record)

def register_workspace_local_app_project_from_contract(
    store: AppStore,
    *,
    workspace_id: str,
    project_root: str,
    project_id: str | None = None,
    now: datetime | None = None,
) -> WorkspaceLocalAppProjectRecord:
    """Parse one canonical app contract file and persist a workspace-local app project record."""
    parsed = parse_app_contract_file(Path(project_root))
    if parsed.contract.distribution.mode != "workspace_local":
        raise AppLifecycleError("Workspace-local app projects must declare distribution.mode `workspace_local`.")
    record = parsed_contract_to_workspace_local_project_record(
        parsed=parsed,
        workspace_id=workspace_id,
        project_root=project_root,
        project_id=project_id,
        now=now,
    )
    return register_workspace_local_app_project(store, record)
