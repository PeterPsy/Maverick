"""Commit app-owned state after runtime cleanup succeeds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.api.platform_state import PlatformState
from core.apps.errors import AppHostingError
from core.shared.entrypoints import run_json_entrypoint


def apply_runtime_cleanup_commit(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    source_root: Path,
    backend_entrypoint: str | None,
    data_root: str,
    parsed,
    result: dict[str, Any],
    cleanup_results: list[dict[str, object]],
) -> None:
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    commit = result.pop("runtime_cleanup_commit", None)
    if commit is None and response_json is not None:
        commit = response_json.pop("runtime_cleanup_commit", None)
    if commit is None:
        return
    if not isinstance(commit, dict):
        raise AppHostingError("Runtime cleanup commit must be an object.")
    action = str(commit.get("action") or "").strip()
    if not action:
        raise AppHostingError("Runtime cleanup commit requires action.")
    if backend_entrypoint is None:
        raise AppHostingError(f"App `{app_id}` requested runtime cleanup commit without a backend entrypoint.")
    payload = commit.get("payload") if isinstance(commit.get("payload"), dict) else {}
    commit_result = run_json_entrypoint(
        source_root / backend_entrypoint,
        payload={
            "surface": "runtime_cleanup_commit",
            "workspace_id": workspace_id,
            "app_id": app_id,
            "data_root": data_root,
            "body": {
                **payload,
                "action": action,
                "runtime_cleanup_results": cleanup_results,
            },
            "runtime_session_id": "",
            "turn_id": "",
        },
        cwd=source_root,
        timeout_seconds=30,
    )
    publish_declared_app_events(
        state.app_event_bus,
        commit_result,
        workspace_id=workspace_id,
        app_id=app_id,
        declared_resources=declared_data_event_resources(parsed.contract.capabilities.data_events),
        remove_from_result=True,
    )
    status_code = int(commit_result.get("status_code", 200))
    if status_code >= 400:
        raise AppHostingError(str(commit_result.get("json") or commit_result))
    result.clear()
    result.update(commit_result)
