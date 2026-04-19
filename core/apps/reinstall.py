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
from core.apps.service_common import (
    _build_workspace_hook_payload,
    _ensure_workspace_app_data_root,
    _parse_version_tuple,
    _write_current_data_state,
)

def _resolve_reinstall_target(store: AppStore, *, workspace_id: str, app_id: str, start_path: Path | None = None):
    try:
        project = store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
    except WorkspaceLocalAppProjectNotFoundError:
        project = None
    if project is not None:
        source_root, parsed = load_contract_from_workspace_project(project, start_path=start_path)
        source_record_id = project.project_id
        source_kind: AppSourceKind = "workspace_local_project"
        persisted_app_id = project.app_id
    else:
        sources = [source for source in store.list_app_sources() if source.app_id == app_id]
        if not sources:
            raise AppLifecycleError(f"No app source is available to reinstall `{app_id}`.")
        latest = sorted(sources, key=lambda item: _parse_version_tuple(item.version))[-1]
        source_root, parsed = load_contract_from_source_record(latest, start_path=start_path)
        source_record_id = latest.source_id
        source_kind = latest.source_kind
        persisted_app_id = latest.app_id
    return source_root, parsed, source_record_id, source_kind, persisted_app_id

def reinstall_workspace_app(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    now: datetime | None = None,
    start_path: Path | None = None,
    validate_existing_data: bool = True,
    repair_existing_data: bool = False,
    migration_required: bool = False,
    observability_store=None,
) -> WorkspaceAppReinstallResult:
    """Reinstall one workspace app and reattach to existing app-owned data when available."""
    data_root = workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    reused_existing_data_root = data_root.exists()
    source_root, parsed, source_record_id, source_kind, persisted_app_id = _resolve_reinstall_target(
        store,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
    )
    ensure_app_compatible(compatibility=parsed.contract.compatibility, workspace_id=workspace_id)
    prepared_data_root = _ensure_workspace_app_data_root(
        workspace_id=workspace_id,
        app_id=persisted_app_id,
        start_path=start_path,
    )
    hook_payload = _build_workspace_hook_payload(
        workspace_id=workspace_id,
        app_id=persisted_app_id,
        data_root=prepared_data_root,
        source_kind=source_kind,
        source_record_id=source_record_id,
        hook_name="reinstall",
        start_path=start_path,
    )
    if reused_existing_data_root:
        run_reactivation_hooks(
            source_root,
            parsed.contract,
            validate_existing_data=validate_existing_data,
            repair_existing_data=repair_existing_data,
            migration_required=migration_required,
            payload=hook_payload,
        )
    status = finalize_install_status(
        source_root=source_root,
        contract=parsed.contract,
        enabled=True,
        payload=hook_payload,
    )
    binding = build_workspace_app_binding_record(
        workspace_id=workspace_id,
        app_id=persisted_app_id,
        source_record_id=source_record_id,
        source_kind=source_kind,
        status=status,
        active_version=parsed.version,
        data_root=str(prepared_data_root),
        now=now,
    )
    binding = store.save_workspace_app_binding(binding)
    _write_current_data_state(
        data_root=prepared_data_root,
        app_id=persisted_app_id,
        app_version=parsed.version,
        data_schema_version=parsed.contract.storage.data_schema_version,
        now=now,
    )
    result = WorkspaceAppReinstallResult(
        binding=binding,
        reused_existing_data_root=reused_existing_data_root,
        validation_requested=validate_existing_data,
        repair_requested=repair_existing_data,
        migration_requested=migration_required,
    )
    if observability_store is not None:
        payload = {
            "workspace_id": workspace_id,
            "app_id": persisted_app_id,
            "reused_existing_data_root": reused_existing_data_root,
            "validation_requested": validate_existing_data,
            "repair_requested": repair_existing_data,
            "migration_requested": migration_required,
        }
        record_platform_audit(
            observability_store,
            action="app.reinstall",
            status="succeeded",
            source_domain="apps",
            detail=f"Reinstalled app `{persisted_app_id}` in workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            app_id=persisted_app_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="app.reinstalled",
            event_plane="workspace",
            source_domain="apps",
            workspace_id=workspace_id,
            app_id=persisted_app_id,
            payload=payload,
        )
    return result
