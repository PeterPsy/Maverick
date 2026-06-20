"""Canonical payload builders for app lifecycle hooks."""

from __future__ import annotations

from pathlib import Path

from core.apps.dependencies import resolve_app_dependencies
from core.apps.store import AppStore

from core.apps.service_common import _build_workspace_hook_payload, _ensure_workspace_app_data_root

def build_app_export_hook_payload(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
) -> dict[str, object]:
    """Build the canonical payload passed to one app export hook."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    return _build_workspace_hook_payload(
        workspace_id=workspace_id,
        app_id=app_id,
        data_root=data_root,
        source_kind=binding.source_kind,
        source_record_id=binding.source_record_id,
        hook_name="workspace_export",
        start_path=start_path,
    )

def build_app_health_hook_payload(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
) -> dict[str, object]:
    """Build the canonical payload passed to one app health hook."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    data_root = _ensure_workspace_app_data_root(workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    payload = _build_workspace_hook_payload(
        workspace_id=workspace_id,
        app_id=app_id,
        data_root=data_root,
        source_kind=binding.source_kind,
        source_record_id=binding.source_record_id,
        hook_name="health_check",
        start_path=start_path,
    )
    payload["app_dependencies"] = _app_dependencies_payload(
        store,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
    )
    return payload


def _app_dependencies_payload(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None,
) -> dict[str, object]:
    try:
        return resolve_app_dependencies(
            store,
            workspace_id=workspace_id,
            consumer_app_id=app_id,
            start_path=start_path,
        )
    except Exception:
        return {"workspace_id": workspace_id, "consumer_app_id": app_id, "status": "blocked", "dependencies": []}
