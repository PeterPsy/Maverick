"""App-hosting services for Phase 4."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Literal

from core.apps.errors import (
    AppCompatibilityError,
    AppDataRootError,
    AppLifecycleError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.models import (
    AppContractDescriptor,
    AppEntrypoints,
    AppFailureSemantics,
    AppHealthContract,
    AppHookTimeouts,
    AppCompatibilityDescriptor,
    AppRollbackSupport,
    AppSourceKind,
    AppSourceRecord,
    WorkspaceAppBindingRecord,
    WorkspaceAppReinstallResult,
    WorkspaceAppStatus,
    WorkspaceLocalAppProjectRecord,
)
from core.apps.paths import external_app_bundles_root, installed_app_root, workspace_app_data_root, workspace_apps_root
from core.apps.store import AppStore
from core.execution_policy.models import ExecutionMode
from core.execution_policy.service import resolve_workspace_execution_profile
from core.shared.version import current_core_version


CURRENT_APP_CONTRACT_VERSION = "1.0"


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _timestamp(now: datetime | None = None) -> str:
    return (now or utcnow()).isoformat()


def _normalize_slug(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")
    return normalized or fallback


def _parse_version(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(version).strip().split("."))
    except ValueError as error:
        raise AppCompatibilityError(f"Unsupported version string `{version}`.") from error


def _ensure_minimum_core_version(minimum_core_version: str) -> None:
    installed_core_version = current_core_version(start_path=Path(__file__))
    if _parse_version(installed_core_version) < _parse_version(minimum_core_version):
        raise AppCompatibilityError(
            f"App requires core version `{minimum_core_version}` but current core is `{installed_core_version}`."
        )


def _ensure_contract_version(contract_version: str) -> None:
    if str(contract_version).strip() != CURRENT_APP_CONTRACT_VERSION:
        raise AppCompatibilityError(
            f"App contract version `{contract_version}` is not supported by core contract `{CURRENT_APP_CONTRACT_VERSION}`."
        )


def _effective_workspace_mode(workspace_id: str) -> ExecutionMode:
    return resolve_workspace_execution_profile(workspace_id).effective_mode


def ensure_app_compatible(*, compatibility: AppCompatibilityDescriptor, workspace_id: str) -> None:
    """Validate the compatibility metadata required by Phase 4 install flows."""
    _ensure_contract_version(compatibility.contract_version)
    _ensure_minimum_core_version(compatibility.minimum_core_version)
    supported_modes = compatibility.supported_workspace_modes or []
    if supported_modes and _effective_workspace_mode(workspace_id) not in supported_modes:
        raise AppCompatibilityError(
            f"App does not support workspace mode `{_effective_workspace_mode(workspace_id)}` for workspace `{workspace_id}`."
        )


def build_app_compatibility(
    *,
    contract_version: str = CURRENT_APP_CONTRACT_VERSION,
    minimum_core_version: str | None = None,
    supported_workspace_modes: list[ExecutionMode] | None = None,
) -> AppCompatibilityDescriptor:
    """Build one app compatibility descriptor."""
    return AppCompatibilityDescriptor(
        contract_version=contract_version,
        minimum_core_version=minimum_core_version or current_core_version(start_path=Path(__file__)),
        supported_workspace_modes=supported_workspace_modes,
    )


def build_app_entrypoints(
    *,
    mcp: str | None = None,
    cli: str | None = None,
    skills_root: str | None = None,
    hooks: dict[str, str] | None = None,
) -> AppEntrypoints:
    """Build app executable entrypoints."""
    return AppEntrypoints(mcp=mcp, cli=cli, skills_root=skills_root, hooks=hooks or {})


def build_app_hook_timeouts(
    *,
    install_seconds: int = 60,
    migrate_seconds: int = 300,
    health_check_seconds: int = 30,
    export_seconds: int = 120,
    import_seconds: int = 120,
) -> AppHookTimeouts:
    """Build lifecycle and health timeout metadata."""
    return AppHookTimeouts(
        install_seconds=install_seconds,
        migrate_seconds=migrate_seconds,
        health_check_seconds=health_check_seconds,
        export_seconds=export_seconds,
        import_seconds=import_seconds,
    )


def build_app_failure_semantics(
    *,
    install_failure: str = "block_activation",
    migrate_failure: str = "preserve_data_mark_unhealthy",
    import_failure: str = "preserve_payload_mark_failed",
) -> AppFailureSemantics:
    """Build failure-semantics metadata."""
    return AppFailureSemantics(
        install_failure=install_failure,
        migrate_failure=migrate_failure,
        import_failure=import_failure,
    )


def build_app_health_contract(*, mode: str = "none", degraded_on_failure: bool = True) -> AppHealthContract:
    """Build health-check contract metadata."""
    return AppHealthContract(mode=mode, degraded_on_failure=degraded_on_failure)


def build_app_rollback_support(*, bundle: bool = False, data: bool = False, repair_only: bool = False) -> AppRollbackSupport:
    """Build rollback support metadata."""
    return AppRollbackSupport(bundle=bundle, data=data, repair_only=repair_only)


def build_app_contract(
    *,
    compatibility: AppCompatibilityDescriptor | None = None,
    entrypoints: AppEntrypoints | None = None,
    hook_timeouts: AppHookTimeouts | None = None,
    failure_semantics: AppFailureSemantics | None = None,
    health_contract: AppHealthContract | None = None,
    rollback_support: AppRollbackSupport | None = None,
) -> AppContractDescriptor:
    """Build an executable app contract descriptor."""
    return AppContractDescriptor(
        compatibility=compatibility or build_app_compatibility(),
        entrypoints=entrypoints or build_app_entrypoints(),
        hook_timeouts=hook_timeouts or build_app_hook_timeouts(),
        failure_semantics=failure_semantics or build_app_failure_semantics(),
        health_contract=health_contract or build_app_health_contract(),
        rollback_support=rollback_support or build_app_rollback_support(),
    )


def build_app_source_record(
    *,
    app_id: str,
    name: str,
    version: str,
    description: str,
    publisher: str,
    source_kind: Literal["platform", "external_bundle"],
    source_path: str,
    contract: AppContractDescriptor | None = None,
    source_id: str | None = None,
    now: datetime | None = None,
) -> AppSourceRecord:
    """Build one installation-level app source record."""
    timestamp = _timestamp(now)
    normalized_app_id = _normalize_slug(app_id, fallback="app")
    return AppSourceRecord(
        source_id=source_id or f"{source_kind}:{normalized_app_id}:{version}",
        app_id=normalized_app_id,
        name=name,
        version=version,
        description=description,
        publisher=publisher,
        source_kind=source_kind,
        source_path=source_path,
        contract=contract or build_app_contract(),
        created_at=timestamp,
        updated_at=timestamp,
    )


def build_workspace_local_app_project_record(
    *,
    workspace_id: str,
    app_id: str,
    name: str,
    version: str,
    description: str,
    publisher: str,
    project_root: str,
    contract: AppContractDescriptor | None = None,
    project_id: str | None = None,
    now: datetime | None = None,
) -> WorkspaceLocalAppProjectRecord:
    """Build one workspace-local app project record."""
    timestamp = _timestamp(now)
    normalized_app_id = _normalize_slug(app_id, fallback="app")
    return WorkspaceLocalAppProjectRecord(
        project_id=project_id or f"{workspace_id}:{normalized_app_id}",
        workspace_id=workspace_id,
        app_id=normalized_app_id,
        name=name,
        version=version,
        description=description,
        publisher=publisher,
        project_root=project_root,
        contract=contract or build_app_contract(),
        created_at=timestamp,
        updated_at=timestamp,
    )


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


def _ensure_workspace_app_data_root(*, workspace_id: str, app_id: str, start_path: Path | None = None) -> Path:
    data_root = workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    data_root.mkdir(parents=True, exist_ok=True)
    if not data_root.is_dir():
        raise AppDataRootError(f"App data root `{data_root}` could not be prepared.")
    return data_root


def _external_source_root(record: AppSourceRecord, start_path: Path | None = None) -> Path:
    root = Path(record.source_path).resolve()
    trusted_platform_root = installed_app_root(app_id=record.app_id, start_path=start_path).resolve()
    if record.source_kind == "platform" and root != trusted_platform_root:
        raise AppLifecycleError(
            f"Platform app `{record.app_id}` must resolve to `{trusted_platform_root}`, got `{root}`."
        )
    if record.source_kind == "external_bundle":
        trusted_bundle_root = external_app_bundles_root(start_path=start_path).resolve()
        if trusted_bundle_root not in root.parents:
            raise AppLifecycleError(
                f"External app bundle `{record.app_id}` must live under trusted root `{trusted_bundle_root}`, got `{root}`."
            )
    if not root.exists():
        raise AppLifecycleError(f"App source root `{root}` does not exist for app `{record.app_id}`.")
    return root


def _resolve_contract_path(source_root: Path, relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    resolved = (source_root / relative_path).resolve()
    if source_root.resolve() not in resolved.parents and resolved != source_root.resolve():
        raise AppLifecycleError(f"Contract path `{relative_path}` escapes source root `{source_root}`.")
    return resolved


def _validate_contract_paths(source_root: Path, contract: AppContractDescriptor) -> None:
    for candidate in (contract.entrypoints.mcp, contract.entrypoints.cli, contract.entrypoints.skills_root, *contract.entrypoints.hooks.values()):
        resolved = _resolve_contract_path(source_root, candidate)
        if resolved is not None and not resolved.exists():
            raise AppLifecycleError(f"Contract entrypoint `{candidate}` does not exist under `{source_root}`.")


def _run_hook(source_root: Path, hook_relative_path: str, *, timeout_seconds: int) -> None:
    hook_path = _resolve_contract_path(source_root, hook_relative_path)
    if hook_path is None:
        return
    try:
        result = subprocess.run(
            [sys.executable, str(hook_path)],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AppLifecycleError(f"Hook `{hook_relative_path}` timed out after {timeout_seconds} seconds.") from error
    if result.returncode != 0:
        raise AppLifecycleError(
            f"Hook `{hook_relative_path}` failed with exit code {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )


def _run_install_hook(source_root: Path, contract: AppContractDescriptor) -> None:
    install_hook = contract.entrypoints.hooks.get("install")
    if install_hook:
        _run_hook(source_root, install_hook, timeout_seconds=contract.hook_timeouts.install_seconds)


def _run_health_check(source_root: Path, contract: AppContractDescriptor) -> bool:
    if contract.health_contract.mode == "none":
        return True
    if contract.health_contract.mode == "hook":
        hook = contract.entrypoints.hooks.get("health_check")
        if not hook:
            raise AppLifecycleError("Health contract requires a `health_check` hook entrypoint.")
        try:
            _run_hook(source_root, hook, timeout_seconds=contract.hook_timeouts.health_check_seconds)
            return True
        except AppLifecycleError:
            return False
    raise AppLifecycleError(f"Unsupported health contract mode `{contract.health_contract.mode}`.")


def _finalize_install_status(
    *,
    source_root: Path,
    contract: AppContractDescriptor,
    enabled: bool,
) -> WorkspaceAppStatus:
    _validate_contract_paths(source_root, contract)
    try:
        _run_install_hook(source_root, contract)
    except AppLifecycleError:
        if contract.failure_semantics.install_failure == "mark_failed":
            return "failed"
        raise
    healthy = _run_health_check(source_root, contract)
    if healthy:
        return "enabled" if enabled else "installed"
    if contract.health_contract.degraded_on_failure:
        return "failed"
    raise AppLifecycleError("App health check failed and the contract does not allow degraded activation.")


def install_external_app(
    store: AppStore,
    *,
    source_id: str,
    workspace_id: str,
    enabled: bool = True,
    now: datetime | None = None,
    start_path: Path | None = None,
) -> WorkspaceAppBindingRecord:
    """Install one installation-level app source into a workspace."""
    source = store.get_app_source(source_id)
    ensure_app_compatible(compatibility=source.contract.compatibility, workspace_id=workspace_id)
    source_root = _external_source_root(source, start_path=start_path)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=source.app_id, start_path=start_path)
    status = _finalize_install_status(source_root=source_root, contract=source.contract, enabled=enabled)
    binding = build_workspace_app_binding_record(
        workspace_id=workspace_id,
        app_id=source.app_id,
        source_record_id=source.source_id,
        source_kind=source.source_kind,
        status=status,
        active_version=source.version,
        data_root=str(data_root),
        now=now,
    )
    return store.save_workspace_app_binding(binding)


def install_workspace_local_app(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    enabled: bool = True,
    now: datetime | None = None,
    start_path: Path | None = None,
) -> WorkspaceAppBindingRecord:
    """Install one workspace-local app project into its owning workspace."""
    project = store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
    if project.workspace_id != workspace_id:
        raise AppLifecycleError(
            f"Workspace-local app project `{app_id}` belongs to workspace `{project.workspace_id}`, not `{workspace_id}`."
        )
    ensure_app_compatible(compatibility=project.contract.compatibility, workspace_id=workspace_id)
    project_root = Path(project.project_root)
    expected_root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path) / project.app_id
    if project_root != expected_root:
        raise AppLifecycleError(
            f"Workspace-local app project `{app_id}` must live under `{expected_root}`, got `{project_root}`."
        )
    if not project_root.exists():
        raise AppLifecycleError(f"Workspace-local app project root `{project_root}` does not exist.")
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=project.app_id, start_path=start_path)
    status = _finalize_install_status(source_root=project_root, contract=project.contract, enabled=enabled)
    binding = build_workspace_app_binding_record(
        workspace_id=workspace_id,
        app_id=project.app_id,
        source_record_id=project.project_id,
        source_kind="workspace_local_project",
        status=status,
        active_version=project.version,
        data_root=str(data_root),
        now=now,
    )
    return store.save_workspace_app_binding(binding)


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
) -> WorkspaceAppBindingRecord:
    """Transition one installed workspace app binding between canonical lifecycle states."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    if target_status == "enabled" and binding.status == "installed":
        updated = replace(binding, status="enabled", updated_at=_timestamp(now))
        return store.save_workspace_app_binding(updated)
    if not _transition_allowed(binding.status, target_status):
        raise AppLifecycleError(
            f"Cannot transition workspace app `{app_id}` in `{workspace_id}` from `{binding.status}` to `{target_status}`."
        )
    updated = replace(binding, status=target_status, updated_at=_timestamp(now))
    return store.save_workspace_app_binding(updated)


def uninstall_workspace_app(store: AppStore, *, workspace_id: str, app_id: str) -> None:
    """Remove one workspace app binding without deleting app-owned data."""
    store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    store.delete_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)


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
) -> WorkspaceAppReinstallResult:
    """Reinstall one workspace app and reattach to existing app-owned data when available."""
    data_root = workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    reused_existing_data_root = data_root.exists()
    if reused_existing_data_root:
        project = None
        try:
            project = store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
        except WorkspaceLocalAppProjectNotFoundError:
            project = None
        if project is not None:
            binding = install_workspace_local_app(
                store,
                workspace_id=workspace_id,
                app_id=app_id,
                enabled=True,
                now=now,
                start_path=start_path,
            )
        else:
            sources = [source for source in store.list_app_sources() if source.app_id == app_id]
            if not sources:
                raise AppLifecycleError(f"No app source is available to reinstall `{app_id}`.")
            latest = sorted(sources, key=lambda item: _parse_version(item.version))[-1]
            binding = install_external_app(
                store,
                source_id=latest.source_id,
                workspace_id=workspace_id,
                enabled=True,
                now=now,
                start_path=start_path,
            )
    else:
        try:
            binding = install_workspace_local_app(
                store,
                workspace_id=workspace_id,
                app_id=app_id,
                enabled=True,
                now=now,
                start_path=start_path,
            )
        except WorkspaceLocalAppProjectNotFoundError:
            sources = [source for source in store.list_app_sources() if source.app_id == app_id]
            if not sources:
                raise AppLifecycleError(f"No app source is available to reinstall `{app_id}`.")
            latest = sorted(sources, key=lambda item: _parse_version(item.version))[-1]
            binding = install_external_app(
                store,
                source_id=latest.source_id,
                workspace_id=workspace_id,
                enabled=True,
                now=now,
                start_path=start_path,
            )
    return WorkspaceAppReinstallResult(
        binding=binding,
        reused_existing_data_root=reused_existing_data_root,
        validation_requested=validate_existing_data,
        repair_requested=repair_existing_data,
        migration_requested=migration_required,
    )
