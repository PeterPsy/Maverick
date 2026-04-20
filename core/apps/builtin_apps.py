"""Bootstrap built-in apps that ship with the Maverick core host."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.store import AppStore
from core.shared.repository import installation_paths
from core.workspaces.store import WorkspaceStore
from core.workspaces.service import ensure_default_workspace_record, ensure_workspace_layout


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
    installed: list[str] = []
    for spec in discover_builtin_apps(start_path=start_path):
        if not spec.source_path.is_dir():
            continue
        source = register_app_source_from_contract(
            app_store,
            source_kind="platform",
            source_path=str(spec.source_path),
            now=now,
        )
        install_store_app(
            app_store,
            source_id=source.source_id,
            workspace_id=workspace_id,
            enabled=True,
            now=now,
            start_path=start_path,
            observability_store=observability_store,
        )
        installed.append(source.app_id)
    return installed


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
