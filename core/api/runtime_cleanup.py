"""Platform-level runtime cleanup helpers for shell and app APIs."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import shutil

from core.api.app_mounts import handle_app_backend
from core.api.platform_state import PlatformState
from core.inter_agent.service import InterAgentService, TERMINAL_RUN_STATUSES
from core.inter_agent.surfaces import inter_agent_payload
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.paths import runtime_session_root
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.runtime_threads import thread_payload
from core.runtime.session_termination import terminate_runtime_session


class RuntimeCleanupError(Exception):
    """Raised when one full runtime cleanup cannot complete."""


def cleanup_runtime_session(
    state: PlatformState,
    *,
    session_id: str,
    reason: str,
    start_path=None,
    publish_thread_events: bool = True,
    allow_hidden_inter_agent_cleanup: bool = False,
) -> dict[str, object]:
    """Fully remove one runtime session, app cleanup metadata, and runtime files."""
    try:
        session = state.runtime_store.get_session(session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return {
            "session_id": session_id,
            "found": False,
            "workspace_id": None,
            "terminated_processes": 0,
            "cancelled_turns": 0,
            "deleted": {"sessions": 0, "turns": 0, "events": 0, "processes": 0, "states": 0, "client_messages": 0},
            "deleted_threads": 0,
            "deleted_thread_ids": [],
            "runtime_root_deleted": False,
        }
    if not allow_hidden_inter_agent_cleanup and not runtime_session_allows_user_thread(session):
        raise RuntimeCleanupError("runtime_session_hidden")
    try:
        runtime_root = runtime_session_root(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            start_path=start_path or state.repository_root,
        )
    except ValueError as error:
        raise RuntimeCleanupError("runtime_session_id_unsafe") from error

    inter_agent_cleanup = _cleanup_inter_agent_runs_for_root_session(
        state,
        workspace_id=session.workspace_id,
        root_session_id=session.session_id,
        reason=reason,
        start_path=start_path or state.repository_root,
    )
    app_cleanup = _cleanup_app_runtime_session_metadata(
        state,
        workspace_id=session.workspace_id,
        session_id=session.session_id,
        start_path=start_path or state.repository_root,
    )
    termination = terminate_runtime_session(
        state.runtime_store,
        session_id=session.session_id,
        reason=reason,
        event_bus=state.runtime_event_bus,
        observability_store=state.observability_store,
        start_path=start_path or state.repository_root,
    )
    deleted = state.runtime_store.delete_session_records(session.session_id)
    deleted_threads = _delete_runtime_threads_for_session(
        state,
        workspace_id=session.workspace_id,
        session_id=session.session_id,
    )
    if publish_thread_events and deleted_threads:
        _publish_deleted_thread_cleanup(state, workspace_id=session.workspace_id, deleted_thread_ids=deleted_threads)
    runtime_root_deleted = _delete_runtime_root(
        runtime_root,
        workspace_id=session.workspace_id,
        session_id=session.session_id,
        start_path=start_path or state.repository_root,
    )
    return {
        **termination,
        "workspace_id": session.workspace_id,
        "deleted": deleted,
        "inter_agent_cleanup": inter_agent_cleanup,
        "app_cleanup": app_cleanup,
        "deleted_threads": len(deleted_threads),
        "deleted_thread_ids": deleted_threads,
        "runtime_root_deleted": runtime_root_deleted,
    }


def _delete_runtime_threads_for_session(
    state: PlatformState,
    *,
    workspace_id: str,
    session_id: str,
) -> list[str]:
    deleted_thread_ids: list[str] = []
    for thread in state.runtime_store.list_threads(workspace_id):
        if thread.runtime_session_id != session_id:
            continue
        if state.runtime_store.delete_thread(thread.thread_id):
            deleted_thread_ids.append(thread.thread_id)
    return deleted_thread_ids


def _cleanup_inter_agent_runs_for_root_session(
    state: PlatformState,
    *,
    workspace_id: str,
    root_session_id: str,
    reason: str,
    start_path,
) -> list[dict[str, object]]:
    service = InterAgentService(state.inter_agent_store)
    results: list[dict[str, object]] = []
    for run in state.inter_agent_store.list_runs(workspace_id):
        if run.root_runtime_session_id != root_session_id or run.status in TERMINAL_RUN_STATUSES:
            continue
        result = service.close_run(
            workspace_id=workspace_id,
            run_id=run.run_id,
            cleanup_runtime_session=lambda session_id, cleanup_reason: cleanup_runtime_session(
                state,
                session_id=session_id,
                reason=cleanup_reason,
                start_path=start_path,
                publish_thread_events=False,
                allow_hidden_inter_agent_cleanup=True,
            ),
            reason=reason,
            terminal_status="cancelled",
            delete_records=True,
        )
        results.append(inter_agent_payload({"run_id": run.run_id, **result}))
    return results


def _publish_deleted_thread_cleanup(
    state: PlatformState,
    *,
    workspace_id: str,
    deleted_thread_ids: list[str],
) -> None:
    threads = sorted(state.runtime_store.list_threads(workspace_id), key=lambda thread: thread.updated_at, reverse=True)
    state.runtime_thread_event_bus.publish(
        workspace_id=workspace_id,
        event={
            "action": "deleted",
            "threads": [thread_payload(thread) for thread in threads],
            "deleted_thread_ids": deleted_thread_ids,
            "deleted_runtime_session_ids": [],
        },
    )


def _cleanup_app_runtime_session_metadata(
    state: PlatformState,
    *,
    workspace_id: str,
    session_id: str,
    start_path,
) -> list[dict[str, object]]:
    cleanup_results: list[dict[str, object]] = []
    for binding in state.app_store.list_workspace_app_bindings(workspace_id):
        if binding.status != "enabled":
            continue
        from core.api.app_registry import resolve_app_surface

        try:
            _binding, _source_root, parsed = resolve_app_surface(
                state,
                workspace_id=workspace_id,
                app_id=binding.app_id,
                start_path=start_path,
            )
        except Exception:
            continue
        if not parsed.contract.permissions.runtime.cleanup_sessions or parsed.contract.entrypoints.backend is None:
            continue
        result = _invoke_runtime_cleanup_backend(
            state,
            workspace_id=workspace_id,
            app_id=binding.app_id,
            session_id=session_id,
            start_path=start_path,
        )
        cleanup_results.append({"app_id": binding.app_id, **result})
    return cleanup_results


def _invoke_runtime_cleanup_backend(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    session_id: str,
    start_path,
) -> dict[str, object]:
    body = {"action": "runtime.cleanup_sessions", "runtime_session_ids": [session_id]}
    payload_bytes = json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {}
    environ = {
        "PATH_INFO": f"/api/apps/{app_id}/backend",
        "REQUEST_METHOD": "POST",
        "CONTENT_LENGTH": str(len(payload_bytes)),
        "CONTENT_TYPE": "application/json",
        "QUERY_STRING": "",
        "wsgi.input": BytesIO(payload_bytes),
    }

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        headers.update(dict(response_headers))
        headers["__status__"] = status

    response_body = b"".join(
        handle_app_backend(
            state,
            environ=environ,
            workspace_id=workspace_id,
            app_id=app_id,
            user=None,
            start_path=start_path,
            start_response=start_response,
            trusted_platform_invocation=True,
        )
    )
    status_code = int(headers.get("__status__", "500 Internal Server Error").split()[0])
    payload = json.loads(response_body.decode("utf-8")) if response_body else {}
    if status_code >= 400:
        detail = str(payload.get("error") or "app_runtime_cleanup_failed")
        raise RuntimeCleanupError(
            f"Failed to clean app `{app_id}` records for runtime session `{session_id}`: {detail}"
        )
    return payload if isinstance(payload, dict) else {}


def _delete_runtime_root(
    runtime_root: Path,
    *,
    workspace_id: str,
    session_id: str,
    start_path,
) -> bool:
    try:
        expected_root = runtime_session_root(
            workspace_id=workspace_id,
            session_id=session_id,
            start_path=start_path,
        ).resolve()
    except ValueError as error:
        raise RuntimeCleanupError("runtime_session_id_unsafe") from error
    resolved_root = runtime_root.resolve(strict=False)
    if resolved_root != expected_root:
        raise RuntimeCleanupError(
            f"Refusing to delete runtime root `{runtime_root}` because it does not match `{expected_root}`."
        )
    if not resolved_root.exists():
        return False
    shutil.rmtree(resolved_root)
    return True
