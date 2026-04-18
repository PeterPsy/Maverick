"""App-hosting services for app installation and enablement."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import shutil

from core.apps.contracts import (
    build_app_compatibility,
    build_app_capabilities,
    build_app_contract,
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
)
from core.apps.errors import (
    AppDataRootError,
    AppLifecycleError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.models import (
    AppSourceKind,
    AppSourceRecord,
    WorkspaceAppBindingRecord,
    WorkspaceAppReinstallResult,
    WorkspaceAppStatus,
    WorkspaceLocalAppProjectRecord,
)
from core.apps.paths import workspace_app_data_root
from core.apps.store import AppStore
from core.apps.lifecycle import (
    ensure_app_compatible,
    finalize_install_status,
    load_contract_from_source_record,
    load_contract_from_workspace_project,
    run_reactivation_hooks,
)
from core.observability.service import record_platform_audit, record_platform_event


def _timestamp(now: datetime | None = None) -> str:
    return (now or utcnow()).isoformat()


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
    parsed = parse_app_contract_file(Path(source_path))
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
    record = parsed_contract_to_workspace_local_project_record(
        parsed=parsed,
        workspace_id=workspace_id,
        project_root=project_root,
        project_id=project_id,
        now=now,
    )
    return register_workspace_local_app_project(store, record)


def _ensure_workspace_app_data_root(*, workspace_id: str, app_id: str, start_path: Path | None = None) -> Path:
    data_root = workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    data_root.mkdir(parents=True, exist_ok=True)
    if not data_root.is_dir():
        raise AppDataRootError(f"App data root `{data_root}` could not be prepared.")
    return data_root


def _parse_version_tuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as error:
        raise AppLifecycleError(f"Unsupported app version `{version}` in reinstall flow.") from error


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


def install_external_app(
    store: AppStore,
    *,
    source_id: str,
    workspace_id: str,
    enabled: bool = True,
    now: datetime | None = None,
    start_path: Path | None = None,
    observability_store=None,
) -> WorkspaceAppBindingRecord:
    """Install one installation-level app source into a workspace."""
    source = store.get_app_source(source_id)
    source_root, parsed = load_contract_from_source_record(source, start_path=start_path)
    ensure_app_compatible(compatibility=parsed.contract.compatibility, workspace_id=workspace_id)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=source.app_id, start_path=start_path)
    status = finalize_install_status(source_root=source_root, contract=parsed.contract, enabled=enabled)
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
    if observability_store is not None:
        payload = {"workspace_id": workspace_id, "app_id": source.app_id, "source_id": source.source_id, "status": saved.status}
        record_platform_audit(
            observability_store,
            action="app.install.external",
            status="succeeded",
            source_domain="apps",
            detail=f"Installed external app `{source.app_id}` into workspace `{workspace_id}`.",
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
    status = finalize_install_status(source_root=project_root, contract=parsed.contract, enabled=enabled)
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
    if reused_existing_data_root:
        run_reactivation_hooks(
            source_root,
            parsed.contract,
            validate_existing_data=validate_existing_data,
            repair_existing_data=repair_existing_data,
            migration_required=migration_required,
        )
    status = finalize_install_status(source_root=source_root, contract=parsed.contract, enabled=True)
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
