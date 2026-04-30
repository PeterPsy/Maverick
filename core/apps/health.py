"""Installed app health probe orchestration."""

from __future__ import annotations

from pathlib import Path

from core.apps.store import AppStore
from core.apps.lifecycle import (
    load_contract_from_source_record,
    load_contract_from_workspace_project,
    run_health_check,
)

from core.apps.hook_payloads import build_app_health_hook_payload

def probe_workspace_app_health(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
) -> tuple[bool, str]:
    """Run the declared health contract for one installed workspace app."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    if binding.source_kind == "workspace_local_project":
        project = store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
        source_root, parsed = load_contract_from_workspace_project(project, start_path=start_path)
    else:
        source = store.get_app_source(binding.source_record_id)
        source_root, parsed = load_contract_from_source_record(source, start_path=start_path)
    healthy = run_health_check(
        source_root,
        parsed.contract,
        payload=build_app_health_hook_payload(store, workspace_id=workspace_id, app_id=app_id, start_path=start_path),
    )
    if healthy:
        return True, "App health contract passed."
    return False, "App health contract failed."
