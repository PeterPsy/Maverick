"""Helpers for resolving app-contributed capability surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

from core.apps.lifecycle import load_contract_from_source_record, load_contract_from_workspace_project
from core.apps.models import ParsedAppContract, WorkspaceAppBindingRecord
from core.apps.store import AppStore


WorkspaceAppSurfaceCache: TypeAlias = dict[
    tuple[str, str],
    tuple[Path, ParsedAppContract],
]


def enabled_workspace_app_bindings(store: AppStore, *, workspace_id: str) -> list[WorkspaceAppBindingRecord]:
    """Return the enabled app bindings for one workspace."""
    return [binding for binding in store.list_workspace_app_bindings(workspace_id) if binding.status == "enabled"]


def resolve_workspace_app_surface(
    store: AppStore,
    *,
    binding: WorkspaceAppBindingRecord,
    start_path: Path | None = None,
    surface_cache: WorkspaceAppSurfaceCache | None = None,
) -> tuple[Path, ParsedAppContract]:
    """Resolve one binding, optionally reusing a request/tick-local snapshot."""
    cache_key = (binding.workspace_id, binding.app_id)
    if surface_cache is not None and cache_key in surface_cache:
        return surface_cache[cache_key]
    if binding.source_kind == "workspace_local_project":
        project = store.get_workspace_local_app_project(workspace_id=binding.workspace_id, app_id=binding.app_id)
        resolved = load_contract_from_workspace_project(project, start_path=start_path)
    else:
        source = store.get_app_source(binding.source_record_id)
        resolved = load_contract_from_source_record(source, start_path=start_path)

    if surface_cache is not None:
        surface_cache[cache_key] = resolved
    return resolved
