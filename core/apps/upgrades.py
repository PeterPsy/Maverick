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
    _timestamp,
    _write_current_data_state,
)

def _resolve_upgrade_target(
    store: AppStore,
    *,
    current_binding: WorkspaceAppBindingRecord,
    target_source_id: str | None,
    rebase_workspace_fork: bool = False,
    start_path: Path | None = None,
) -> tuple[Path, object, str, AppSourceKind]:
    if current_binding.source_kind == "workspace_local_project" and target_source_id is not None and not rebase_workspace_fork:
        raise AppLifecycleError(
            "Workspace-local app forks cannot be upgraded to store sources without an explicit rebase."
        )
    if current_binding.source_kind == "workspace_local_project" and target_source_id is None:
        project = store.get_workspace_local_app_project(
            workspace_id=current_binding.workspace_id,
            app_id=current_binding.app_id,
        )
        source_root, parsed = load_contract_from_workspace_project(project, start_path=start_path)
        return source_root, parsed, project.project_id, "workspace_local_project"

    if target_source_id is not None:
        source = store.get_app_source(target_source_id)
    else:
        candidate_sources = [
            source
            for source in store.list_app_sources()
            if source.app_id == current_binding.app_id and _parse_version_tuple(source.version) > _parse_version_tuple(current_binding.active_version)
        ]
        if not candidate_sources:
            raise AppLifecycleError(f"No newer app source is available to upgrade `{current_binding.app_id}`.")
        source = sorted(candidate_sources, key=lambda item: _parse_version_tuple(item.version))[-1]
    if source.app_id != current_binding.app_id:
        raise AppLifecycleError(
            f"Cannot upgrade app `{current_binding.app_id}` using source `{source.source_id}` for app `{source.app_id}`."
        )
    source_root, parsed = load_contract_from_source_record(source, start_path=start_path)
    return source_root, parsed, source.source_id, source.source_kind

def upgrade_workspace_app(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    target_source_id: str | None = None,
    now: datetime | None = None,
    start_path: Path | None = None,
    rebase_workspace_fork: bool = False,
    observability_store=None,
) -> WorkspaceAppUpgradeResult:
    """Upgrade one installed workspace app, rolling back the bundle when declared."""
    current = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    source_root, parsed, source_record_id, source_kind = _resolve_upgrade_target(
        store,
        current_binding=current,
        target_source_id=target_source_id,
        rebase_workspace_fork=rebase_workspace_fork,
        start_path=start_path,
    )
    if parsed.version == current.active_version and source_record_id == current.source_record_id:
        raise AppLifecycleError(f"Workspace app `{app_id}` is already on version `{parsed.version}`.")
    ensure_app_compatible(compatibility=parsed.contract.compatibility, workspace_id=workspace_id)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    existing_state = read_app_data_state(data_root)
    migration_required = (
        existing_state is not None and existing_state.data_schema_version != parsed.contract.storage.data_schema_version
    )
    updating = replace(current, status="updating", updated_at=_timestamp(now))
    store.save_workspace_app_binding(updating)
    try:
        if parsed.contract.lifecycle.upgrade:
            run_lifecycle_hook(
                source_root,
                parsed.contract,
                hook_name="upgrade",
                payload=_build_workspace_hook_payload(
                    workspace_id=workspace_id,
                    app_id=app_id,
                    data_root=data_root,
                    source_kind=source_kind,
                    source_record_id=source_record_id,
                    hook_name="upgrade",
                    start_path=start_path,
                ),
            )
        if migration_required:
            if not parsed.contract.lifecycle.migrate:
                raise AppLifecycleError(
                    f"Upgrade to `{parsed.version}` requires data migration but app `{app_id}` does not declare `migrate`."
                )
            run_lifecycle_hook(
                source_root,
                parsed.contract,
                hook_name="migrate",
                payload=_build_workspace_hook_payload(
                    workspace_id=workspace_id,
                    app_id=app_id,
                    data_root=data_root,
                    source_kind=source_kind,
                    source_record_id=source_record_id,
                    hook_name="migrate",
                    start_path=start_path,
                ),
            )
        healthy = run_health_check(
            source_root,
            parsed.contract,
            payload=_build_workspace_hook_payload(
                workspace_id=workspace_id,
                app_id=app_id,
                data_root=data_root,
                source_kind=source_kind,
                source_record_id=source_record_id,
                hook_name="health_check",
                start_path=start_path,
            ),
        )
        if not healthy:
            raise AppLifecycleError(f"Upgraded app `{app_id}` failed its health contract.")
        next_status: WorkspaceAppStatus = "enabled" if current.status == "enabled" else "disabled"
        upgraded = replace(
            current,
            source_record_id=source_record_id,
            source_kind=source_kind,
            status=next_status,
            active_version=parsed.version,
            updated_at=_timestamp(now),
        )
        saved = store.save_workspace_app_binding(upgraded)
        _write_current_data_state(
            data_root=data_root,
            app_id=app_id,
            app_version=parsed.version,
            data_schema_version=parsed.contract.storage.data_schema_version,
            now=now,
        )
        if observability_store is not None:
            payload = {
                "workspace_id": workspace_id,
                "app_id": app_id,
                "from_version": current.active_version,
                "to_version": parsed.version,
                "migration_ran": migration_required,
                "rolled_back": False,
            }
            record_platform_audit(
                observability_store,
                action="app.upgrade",
                status="succeeded",
                source_domain="apps",
                detail=f"Upgraded app `{app_id}` in workspace `{workspace_id}` to `{parsed.version}`.",
                workspace_id=workspace_id,
                app_id=app_id,
                payload=payload,
            )
            record_platform_event(
                observability_store,
                event_type="app.upgraded",
                event_plane="workspace",
                source_domain="apps",
                workspace_id=workspace_id,
                app_id=app_id,
                payload=payload,
            )
        return WorkspaceAppUpgradeResult(
            binding=saved,
            previous_version=current.active_version,
            target_version=parsed.version,
            migration_ran=migration_required,
            rolled_back=False,
        )
    except AppLifecycleError:
        rollback_status: WorkspaceAppStatus = "rolled_back" if parsed.contract.rollback_support.bundle else "failed"
        recovered = replace(current, status=rollback_status, updated_at=_timestamp(now))
        saved = store.save_workspace_app_binding(recovered)
        if observability_store is not None:
            payload = {
                "workspace_id": workspace_id,
                "app_id": app_id,
                "from_version": current.active_version,
                "to_version": parsed.version,
                "migration_ran": migration_required,
                "rolled_back": rollback_status == "rolled_back",
            }
            record_platform_audit(
                observability_store,
                action="app.upgrade",
                status="failed",
                source_domain="apps",
                detail=f"Upgrade of app `{app_id}` in workspace `{workspace_id}` failed.",
                workspace_id=workspace_id,
                app_id=app_id,
                payload=payload,
            )
            record_platform_event(
                observability_store,
                event_type="app.upgrade.failed",
                event_plane="workspace",
                source_domain="apps",
                workspace_id=workspace_id,
                app_id=app_id,
                payload=payload,
            )
        if rollback_status == "rolled_back":
            return WorkspaceAppUpgradeResult(
                binding=saved,
                previous_version=current.active_version,
                target_version=parsed.version,
                migration_ran=migration_required,
                rolled_back=True,
            )
        raise
