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

from core.apps.registration import build_workspace_app_binding_record
from core.apps.service_common import _build_workspace_hook_payload, _ensure_workspace_app_data_root, _write_current_data_state

def install_store_app(
    store: AppStore,
    *,
    source_id: str,
    workspace_id: str,
    enabled: bool = True,
    now: datetime | None = None,
    start_path: Path | None = None,
    observability_store=None,
) -> WorkspaceAppBindingRecord:
    """Install one server app store source into a workspace."""
    source = store.get_app_source(source_id)
    source_root, parsed = load_contract_from_source_record(source, start_path=start_path)
    ensure_app_compatible(compatibility=parsed.contract.compatibility, workspace_id=workspace_id)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=source.app_id, start_path=start_path)
    status = finalize_install_status(
        source_root=source_root,
        contract=parsed.contract,
        enabled=enabled,
        payload=_build_workspace_hook_payload(
            workspace_id=workspace_id,
            app_id=source.app_id,
            data_root=data_root,
            source_kind=source.source_kind,
            source_record_id=source.source_id,
            hook_name="install",
            start_path=start_path,
        ),
    )
    binding = build_workspace_app_binding_record(
        workspace_id=workspace_id,
        app_id=source.app_id,
        source_record_id=source.source_id,
        source_kind=source.source_kind,
        status=status,
        active_version=parsed.version,
        data_root=str(data_root),
        now=now,
    )
    saved = store.save_workspace_app_binding(binding)
    _write_current_data_state(
        data_root=data_root,
        app_id=source.app_id,
        app_version=parsed.version,
        data_schema_version=parsed.contract.storage.data_schema_version,
        now=now,
    )
    if observability_store is not None:
        payload = {"workspace_id": workspace_id, "app_id": source.app_id, "source_id": source.source_id, "status": saved.status}
        record_platform_audit(
            observability_store,
            action="app.install.store",
            status="succeeded",
            source_domain="apps",
            detail=f"Installed store app `{source.app_id}` into workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            app_id=source.app_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="app.installed",
            event_plane="workspace",
            source_domain="apps",
            workspace_id=workspace_id,
            app_id=source.app_id,
            payload=payload,
        )
    return saved

def install_workspace_local_app(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    enabled: bool = True,
    now: datetime | None = None,
    start_path: Path | None = None,
    observability_store=None,
) -> WorkspaceAppBindingRecord:
    """Install one workspace-local app project into its owning workspace."""
    project = store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
    if project.workspace_id != workspace_id:
        raise AppLifecycleError(
            f"Workspace-local app project `{app_id}` belongs to workspace `{project.workspace_id}`, not `{workspace_id}`."
        )
    project_root, parsed = load_contract_from_workspace_project(project, start_path=start_path)
    ensure_app_compatible(compatibility=parsed.contract.compatibility, workspace_id=workspace_id)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=project.app_id, start_path=start_path)
    status = finalize_install_status(
        source_root=project_root,
        contract=parsed.contract,
        enabled=enabled,
        payload=_build_workspace_hook_payload(
            workspace_id=workspace_id,
            app_id=project.app_id,
            data_root=data_root,
            source_kind="workspace_local_project",
            source_record_id=project.project_id,
            hook_name="install",
            start_path=start_path,
        ),
    )
    binding = build_workspace_app_binding_record(
        workspace_id=workspace_id,
        app_id=project.app_id,
        source_record_id=project.project_id,
        source_kind="workspace_local_project",
        status=status,
        active_version=parsed.version,
        data_root=str(data_root),
        now=now,
    )
    saved = store.save_workspace_app_binding(binding)
    _write_current_data_state(
        data_root=data_root,
        app_id=project.app_id,
        app_version=parsed.version,
        data_schema_version=parsed.contract.storage.data_schema_version,
        now=now,
    )
    if observability_store is not None:
        payload = {"workspace_id": workspace_id, "app_id": project.app_id, "project_id": project.project_id, "status": saved.status}
        record_platform_audit(
            observability_store,
            action="app.install.workspace_local",
            status="succeeded",
            source_domain="apps",
            detail=f"Installed workspace-local app `{project.app_id}` in workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            app_id=project.app_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="app.installed",
            event_plane="workspace",
            source_domain="apps",
            workspace_id=workspace_id,
            app_id=project.app_id,
            payload=payload,
        )
    return saved
