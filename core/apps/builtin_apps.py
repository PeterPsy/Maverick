"""Bootstrap built-in apps that ship with the Maverick core host."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import logging
from pathlib import Path

from core.apps.errors import AppCompatibilityError, AppContractValidationError, WorkspaceAppBindingNotFoundError
from core.apps.models import AppSourceRecord
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.service_common import _ensure_workspace_app_data_root, _write_current_data_state
from core.apps.store import AppStore
from core.shared.repository import installation_paths
from core.workspaces.store import WorkspaceStore
from core.workspaces.service import ensure_default_workspace_record, ensure_workspace_layout


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltinAppSpec:
    """Describe one built-in app that should exist on first boot."""

    app_id: str
    source_path: Path


def discover_builtin_apps(*, start_path: Path | None = None) -> list[BuiltinAppSpec]:
    """Return the built-in apps shipped in the repository app root."""
    paths = installation_paths(start_path=start_path)
    if not paths.apps_root.is_dir():
        return []
    specs: list[BuiltinAppSpec] = []
    for source_path in sorted(path for path in paths.apps_root.iterdir() if path.is_dir()):
        if (source_path / "app_contract.json").is_file():
            specs.append(BuiltinAppSpec(app_id=source_path.name, source_path=source_path))
    return specs


def register_and_install_builtin_apps(
    app_store: AppStore,
    workspace_store: WorkspaceStore,
    *,
    workspace_id: str = "default",
    start_path: Path | None = None,
    now: datetime | None = None,
    observability_store=None,
) -> list[str]:
    """Ensure built-in apps are known and enabled in one workspace."""
    ensure_default_workspace_record(workspace_store, now=now)
    ensured: list[str] = []
    for spec in discover_builtin_apps(start_path=start_path):
        if not spec.source_path.is_dir():
            continue
        try:
            source = register_app_source_from_contract(
                app_store,
                source_kind="platform",
                source_path=str(spec.source_path),
                now=now,
            )
        except AppContractValidationError:
            continue
        if _current_builtin_binding_exists(
            app_store,
            source=source,
            workspace_id=workspace_id,
            enabled=True,
            start_path=start_path,
            now=now,
        ):
            ensured.append(source.app_id)
            continue
        try:
            install_store_app(
                app_store,
                source_id=source.source_id,
                workspace_id=workspace_id,
                enabled=True,
                now=now,
                start_path=start_path,
                observability_store=observability_store,
            )
        except AppCompatibilityError as error:
            logger.warning(
                "Skipping built-in app %s for workspace %s: %s",
                source.app_id,
                workspace_id,
                error,
            )
            continue
        ensured.append(source.app_id)
    return ensured


def _current_builtin_binding_exists(
    app_store: AppStore,
    *,
    source: AppSourceRecord,
    workspace_id: str,
    enabled: bool,
    start_path: Path | None,
    now: datetime | None,
) -> bool:
    local_app_id = source.app_id
    expected_status = "enabled" if enabled else "installed"
    try:
        binding = app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=local_app_id)
    except WorkspaceAppBindingNotFoundError:
        return False
    if (
        binding.source_record_id != source.source_id
        or binding.source_kind != source.source_kind
        or binding.active_version != source.version
        or binding.status != expected_status
    ):
        return False
    data_root = _ensure_workspace_app_data_root(
        workspace_id=workspace_id,
        app_id=local_app_id,
        start_path=start_path,
    )
    updated = replace(
        binding,
        data_root=str(data_root),
        public_app_id=source.public_app_id or source.app_id,
        local_app_id=local_app_id,
        mount_app_id=local_app_id,
    )
    if updated != binding:
        app_store.save_workspace_app_binding(updated)
    _write_current_data_state(
        data_root=data_root,
        app_id=local_app_id,
        app_version=source.version,
        data_schema_version=source.contract.storage.data_schema_version,
        now=now,
    )
    return True


def register_and_install_builtin_apps_for_active_workspaces(
    app_store: AppStore,
    workspace_store: WorkspaceStore,
    *,
    start_path: Path | None = None,
    now: datetime | None = None,
    observability_store=None,
) -> dict[str, list[str]]:
    """Ensure built-in apps are enabled in every active workspace registry record."""
    ensure_default_workspace_record(workspace_store, now=now)
    installed_by_workspace: dict[str, list[str]] = {}
    for workspace in workspace_store.list_workspaces():
        if workspace.status != "active":
            continue
        ensure_workspace_layout(workspace.workspace_id, start_path=start_path)
        installed_by_workspace[workspace.workspace_id] = register_and_install_builtin_apps(
            app_store,
            workspace_store,
            workspace_id=workspace.workspace_id,
            start_path=start_path,
            now=now,
            observability_store=observability_store,
        )
    return installed_by_workspace
