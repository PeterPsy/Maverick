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

from core.apps.service_common import _timestamp

def _transition_allowed(current: WorkspaceAppStatus, target: WorkspaceAppStatus) -> bool:
    allowed: dict[WorkspaceAppStatus, set[WorkspaceAppStatus]] = {
        "installed": {"enabled", "disabled", "failed", "updating"},
        "enabled": {"disabled", "failed", "updating"},
        "disabled": {"enabled", "failed", "updating"},
        "failed": {"disabled", "rolled_back"},
        "updating": {"enabled", "failed", "rolled_back"},
        "rolled_back": {"enabled", "disabled"},
    }
    return target in allowed[current]

def transition_workspace_app_status(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    target_status: WorkspaceAppStatus,
    now: datetime | None = None,
    observability_store=None,
) -> WorkspaceAppBindingRecord:
    """Transition one installed workspace app binding between canonical lifecycle states."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    if target_status == "enabled" and binding.status == "installed":
        updated = replace(binding, status="enabled", updated_at=_timestamp(now))
        saved = store.save_workspace_app_binding(updated)
        if observability_store is not None:
            payload = {"workspace_id": workspace_id, "app_id": app_id, "from_status": binding.status, "to_status": saved.status}
            record_platform_audit(
                observability_store,
                action="app.status.transition",
                status="succeeded",
                source_domain="apps",
                detail=f"Transitioned app `{app_id}` to `{saved.status}`.",
                workspace_id=workspace_id,
                app_id=app_id,
                payload=payload,
            )
            record_platform_event(
                observability_store,
                event_type="app.status.transitioned",
                event_plane="workspace",
                source_domain="apps",
                workspace_id=workspace_id,
                app_id=app_id,
                payload=payload,
            )
        return saved
    if not _transition_allowed(binding.status, target_status):
        raise AppLifecycleError(
            f"Cannot transition workspace app `{app_id}` in `{workspace_id}` from `{binding.status}` to `{target_status}`."
        )
    updated = replace(binding, status=target_status, updated_at=_timestamp(now))
    saved = store.save_workspace_app_binding(updated)
    if observability_store is not None:
        payload = {"workspace_id": workspace_id, "app_id": app_id, "from_status": binding.status, "to_status": saved.status}
        record_platform_audit(
            observability_store,
            action="app.status.transition",
            status="succeeded",
            source_domain="apps",
            detail=f"Transitioned app `{app_id}` to `{saved.status}`.",
            workspace_id=workspace_id,
            app_id=app_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="app.status.transitioned",
            event_plane="workspace",
            source_domain="apps",
            workspace_id=workspace_id,
            app_id=app_id,
            payload=payload,
        )
    return saved

def uninstall_workspace_app(store: AppStore, *, workspace_id: str, app_id: str, observability_store=None) -> None:
    """Remove one workspace app binding without deleting app-owned data."""
    store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    store.delete_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    if observability_store is not None:
        payload = {"workspace_id": workspace_id, "app_id": app_id}
        record_platform_audit(
            observability_store,
            action="app.uninstall",
            status="succeeded",
            source_domain="apps",
            detail=f"Uninstalled app `{app_id}` from workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            app_id=app_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="app.uninstalled",
            event_plane="workspace",
            source_domain="apps",
            workspace_id=workspace_id,
            app_id=app_id,
            payload=payload,
        )

def purge_workspace_app_data(*, workspace_id: str, app_id: str, start_path: Path | None = None) -> Path:
    """Delete the persisted app-owned data root for one workspace app."""
    data_root = workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    if data_root.exists():
        shutil.rmtree(data_root)
    return data_root
