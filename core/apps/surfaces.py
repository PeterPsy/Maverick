"""Helpers for resolving app-contributed capability surfaces."""

from __future__ import annotations

from pathlib import Path

from core.apps.lifecycle import load_contract_from_source_record, load_contract_from_workspace_project
from core.apps.models import ParsedAppContract, WorkspaceAppBindingRecord
from core.apps.store import AppStore


def enabled_workspace_app_bindings(store: AppStore, *, workspace_id: str) -> list[WorkspaceAppBindingRecord]:
    """Return the enabled app bindings for one workspace."""
    return [binding for binding in store.list_workspace_app_bindings(workspace_id) if binding.status == "enabled"]


def resolve_workspace_app_surface(
    store: AppStore,
    *,
    binding: WorkspaceAppBindingRecord,
    start_path: Path | None = None,
) -> tuple[Path, ParsedAppContract]:
    """Resolve one enabled workspace app binding to its source root and parsed contract."""
    if binding.source_kind == "workspace_local_project":
        project = store.get_workspace_local_app_project(workspace_id=binding.workspace_id, app_id=binding.app_id)
        return load_contract_from_workspace_project(project, start_path=start_path)

    source = store.get_app_source(binding.source_record_id)
    return load_contract_from_source_record(source, start_path=start_path)
