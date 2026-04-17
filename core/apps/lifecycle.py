"""Executable app-contract lifecycle helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from core.apps.contracts import CURRENT_APP_CONTRACT_VERSION, parse_app_contract_file
from core.apps.errors import AppCompatibilityError, AppLifecycleError
from core.apps.models import (
    AppCompatibilityDescriptor,
    AppContractDescriptor,
    AppSourceRecord,
    ParsedAppContract,
    WorkspaceAppStatus,
    WorkspaceLocalAppProjectRecord,
)
from core.apps.paths import external_app_bundles_root, installed_app_root, workspace_apps_root
from core.execution_policy.models import ExecutionMode
from core.execution_policy.service import resolve_workspace_execution_profile
from core.shared.version import current_core_version


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
    """Validate compatibility metadata for one workspace install target."""
    _ensure_contract_version(compatibility.contract_version)
    _ensure_minimum_core_version(compatibility.minimum_core_version)
    supported_modes = compatibility.supported_workspace_modes or []
    if supported_modes and _effective_workspace_mode(workspace_id) not in supported_modes:
        raise AppCompatibilityError(
            f"App does not support workspace mode `{_effective_workspace_mode(workspace_id)}` for workspace `{workspace_id}`."
        )


def source_root_for_record(record: AppSourceRecord, *, start_path: Path | None = None) -> Path:
    """Resolve and validate one installation-level app source root."""
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


def source_root_for_workspace_project(
    record: WorkspaceLocalAppProjectRecord,
    *,
    start_path: Path | None = None,
) -> Path:
    """Resolve and validate one workspace-local app project root."""
    project_root = Path(record.project_root)
    expected_root = workspace_apps_root(workspace_id=record.workspace_id, start_path=start_path) / record.app_id
    if project_root != expected_root:
        raise AppLifecycleError(
            f"Workspace-local app project `{record.app_id}` must live under `{expected_root}`, got `{project_root}`."
        )
    if not project_root.exists():
        raise AppLifecycleError(f"Workspace-local app project root `{project_root}` does not exist.")
    return project_root


def load_contract_from_source_record(record: AppSourceRecord, *, start_path: Path | None = None) -> tuple[Path, ParsedAppContract]:
    """Load and validate the canonical contract file for one installation-level app source."""
    source_root = source_root_for_record(record, start_path=start_path)
    parsed = parse_app_contract_file(source_root)
    if parsed.app_id != record.app_id:
        raise AppLifecycleError(
            f"App source `{record.source_id}` persisted app_id `{record.app_id}` but contract declares `{parsed.app_id}`."
        )
    return source_root, parsed


def load_contract_from_workspace_project(
    record: WorkspaceLocalAppProjectRecord,
    *,
    start_path: Path | None = None,
) -> tuple[Path, ParsedAppContract]:
    """Load and validate the canonical contract file for one workspace-local project."""
    project_root = source_root_for_workspace_project(record, start_path=start_path)
    parsed = parse_app_contract_file(project_root)
    if parsed.app_id != record.app_id:
        raise AppLifecycleError(
            f"Workspace-local project `{record.project_id}` persisted app_id `{record.app_id}` but contract declares `{parsed.app_id}`."
        )
    return project_root, parsed


def _run_hook(source_root: Path, hook_relative_path: str, *, timeout_seconds: int) -> None:
    hook_path = (source_root / hook_relative_path).resolve()
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


def run_lifecycle_hook(source_root: Path, contract: AppContractDescriptor, *, hook_name: str) -> None:
    """Run one declared lifecycle hook with its configured timeout."""
    hook_path = contract.entrypoints.hooks.get(hook_name)
    if not hook_path:
        return
    timeout_by_hook = {
        "install": contract.hook_timeouts.install_seconds,
        "upgrade": contract.hook_timeouts.upgrade_seconds,
        "migrate": contract.hook_timeouts.migrate_seconds,
        "export": contract.hook_timeouts.export_seconds,
        "import": contract.hook_timeouts.import_seconds,
        "validate_after_import": contract.hook_timeouts.validate_after_import_seconds,
        "repair_after_import": contract.hook_timeouts.repair_after_import_seconds,
        "health_check": contract.hook_timeouts.health_check_seconds,
    }
    timeout_seconds = timeout_by_hook.get(hook_name)
    if timeout_seconds is None:
        raise AppLifecycleError(f"No timeout is configured for lifecycle hook `{hook_name}`.")
    _run_hook(source_root, hook_path, timeout_seconds=timeout_seconds)


def run_reactivation_hooks(
    source_root: Path,
    contract: AppContractDescriptor,
    *,
    validate_existing_data: bool,
    repair_existing_data: bool,
    migration_required: bool,
) -> None:
    """Run requested pre-reactivation hooks against existing app-owned data."""
    if migration_required:
        if not contract.lifecycle.migrate:
            raise AppLifecycleError("Reinstall requested migration but the app contract does not support `migrate`.")
        run_lifecycle_hook(source_root, contract, hook_name="migrate")
    if validate_existing_data:
        if contract.lifecycle.validate_after_import:
            run_lifecycle_hook(source_root, contract, hook_name="validate_after_import")
    if repair_existing_data:
        if not contract.lifecycle.repair_after_import:
            raise AppLifecycleError(
                "Reinstall requested repair but the app contract does not support `repair_after_import`."
            )
        run_lifecycle_hook(source_root, contract, hook_name="repair_after_import")


def run_health_check(source_root: Path, contract: AppContractDescriptor) -> bool:
    """Execute one health contract and return whether the app is healthy."""
    if contract.health_contract.mode == "none":
        return True
    if contract.health_contract.mode == "hook":
        hook = contract.entrypoints.hooks.get("health_check")
        if not hook:
            raise AppLifecycleError("Health contract requires a `health_check` hook entrypoint.")
        try:
            run_lifecycle_hook(source_root, contract, hook_name="health_check")
            return True
        except AppLifecycleError:
            return False
    raise AppLifecycleError(f"Unsupported health contract mode `{contract.health_contract.mode}`.")


def finalize_install_status(
    *,
    source_root: Path,
    contract: AppContractDescriptor,
    enabled: bool,
) -> WorkspaceAppStatus:
    """Run the install + health sequence and return the resulting binding status."""
    try:
        run_lifecycle_hook(source_root, contract, hook_name="install")
    except AppLifecycleError:
        if contract.failure_semantics.install_failure == "mark_failed":
            return "failed"
        raise
    healthy = run_health_check(source_root, contract)
    if healthy:
        return "enabled" if enabled else "installed"
    if contract.health_contract.degraded_on_failure:
        return "failed"
    raise AppLifecycleError("App health check failed and the contract does not allow degraded activation.")
