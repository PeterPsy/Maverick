"""Bootstrap built-in apps that ship with the Maverick core host."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.apps.service import install_external_app, register_app_source_from_contract
from core.apps.store import AppStore
from core.shared.repository import installation_paths
from core.workspaces.store import WorkspaceStore
from core.workspaces.service import ensure_default_workspace_record


@dataclass(frozen=True)
class BuiltinAppSpec:
    """Describe one built-in app that should exist on first boot."""

    app_id: str
    source_path: Path


def discover_builtin_apps(*, start_path: Path | None = None) -> list[BuiltinAppSpec]:
    """Return the built-in apps shipped in the repository app root."""
    paths = installation_paths(start_path=start_path)
    app_ids = ("base-shell", "chat")
    return [BuiltinAppSpec(app_id=app_id, source_path=paths.apps_root / app_id) for app_id in app_ids]


def register_and_install_builtin_apps(
    app_store: AppStore,
    workspace_store: WorkspaceStore,
    *,
    workspace_id: str = "default",
    start_path: Path | None = None,
    now: datetime | None = None,
    observability_store=None,
) -> list[str]:
    """Ensure first-boot built-in apps are known and enabled in the default workspace."""
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
        install_external_app(
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
