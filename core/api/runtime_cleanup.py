"""Platform-level runtime cleanup helpers for shell and app APIs."""

from __future__ import annotations

from pathlib import Path
import shutil
import time

from core.api.platform_state import PlatformState
from core.api.runtime_cleanup_errors import RuntimeCleanupError
from core.api.runtime_cleanup_hooks import cleanup_app_runtime_session_metadata
from core.inter_agent.service import InterAgentService, TERMINAL_RUN_STATUSES
from core.inter_agent.surfaces import inter_agent_payload
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.paths import runtime_session_root
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.runtime_threads import thread_payload
from core.runtime.session_termination import terminate_runtime_session


def cleanup_runtime_session(
    state: PlatformState,
    *,
    session_id: str,
    reason: str,
    start_path=None,
    publish_thread_events: bool = True,
    allow_hidden_inter_agent_cleanup: bool = False,
    allow_hidden_prepared_chat_cleanup: bool = False,
    delete_threads: bool = True,
    cleanup_inter_agent_runs: bool = True,
    cleanup_app_metadata: bool = True,
    defer_persistence_cleanup: bool = False,
) -> dict[str, object]:
    """Fully remove one runtime session, app cleanup metadata, and runtime files."""
    started_at = time.perf_counter()
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
    if not runtime_session_allows_user_thread(session):
        hidden_prepared_chat_allowed = (
            allow_hidden_prepared_chat_cleanup
            and session.session_kind == "chat_root"
            and session.thread_visibility == "hidden"
        )
        if not allow_hidden_inter_agent_cleanup and not hidden_prepared_chat_allowed:
            raise RuntimeCleanupError("runtime_session_hidden")
    try:
        runtime_root = runtime_session_root(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            start_path=start_path or state.repository_root,
        )
    except ValueError as error:
        raise RuntimeCleanupError("runtime_session_id_unsafe") from error
    validated_at = time.perf_counter()

    inter_agent_cleanup = (
        _cleanup_inter_agent_runs_for_root_session(
            state,
            workspace_id=session.workspace_id,
            root_session_id=session.session_id,
            reason=reason,
            start_path=start_path or state.repository_root,
        )
        if cleanup_inter_agent_runs
        else []
    )
    inter_agent_finished_at = time.perf_counter()
    app_cleanup = (
        cleanup_app_runtime_session_metadata(
            state,
            workspace_id=session.workspace_id,
            session_ids=[session.session_id],
            start_path=start_path or state.repository_root,
        )
        if cleanup_app_metadata
        else []
    )
    app_cleanup_finished_at = time.perf_counter()
    termination = terminate_runtime_session(
        state.runtime_store,
        session_id=session.session_id,
        reason=reason,
        event_bus=state.runtime_event_bus,
        observability_store=state.observability_store,
        start_path=start_path or state.repository_root,
    )
    termination_finished_at = time.perf_counter()
    tool_ledger = getattr(state, "runtime_tool_ledger", None)
    deleted_private_payloads = (
        tool_ledger.delete_session_private_payloads(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
        )
        if tool_ledger is not None
        else 0
    )
    deleted = (
        {"tool_private_payloads": deleted_private_payloads}
        if defer_persistence_cleanup
        else state.runtime_store.delete_session_records(session.session_id)
    )
    if not defer_persistence_cleanup:
        deleted["tool_private_payloads"] = deleted_private_payloads
    records_finished_at = time.perf_counter()
    deleted_threads = (
        _delete_runtime_threads_for_session(
            state,
            workspace_id=session.workspace_id,
            session_id=session.session_id,
        )
        if delete_threads and not defer_persistence_cleanup
        else []
    )
    threads_finished_at = time.perf_counter()
    if publish_thread_events and deleted_threads:
        _publish_deleted_thread_cleanup(state, workspace_id=session.workspace_id, deleted_thread_ids=deleted_threads)
    runtime_root_deleted = (
        False
        if defer_persistence_cleanup
        else _delete_runtime_root(
            runtime_root,
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            start_path=start_path or state.repository_root,
        )
    )
    filesystem_finished_at = time.perf_counter()
    return {
        **termination,
        "workspace_id": session.workspace_id,
        "deleted": deleted,
        "inter_agent_cleanup": inter_agent_cleanup,
        "app_cleanup": app_cleanup,
        "deleted_threads": len(deleted_threads),
        "deleted_thread_ids": deleted_threads,
        "runtime_root_deleted": runtime_root_deleted,
        "timings_ms": {
            "session_validation": _elapsed_ms(started_at, validated_at),
            "inter_agent_cleanup": _elapsed_ms(validated_at, inter_agent_finished_at),
            "app_hooks": _elapsed_ms(inter_agent_finished_at, app_cleanup_finished_at),
            "termination": _elapsed_ms(app_cleanup_finished_at, termination_finished_at),
            "record_deletion": _elapsed_ms(termination_finished_at, records_finished_at),
            "thread_catalog": _elapsed_ms(records_finished_at, threads_finished_at),
            "filesystem": _elapsed_ms(threads_finished_at, filesystem_finished_at),
            "total": _elapsed_ms(started_at, filesystem_finished_at),
        },
    }


def _delete_runtime_threads_for_session(
    state: PlatformState,
    *,
    workspace_id: str,
    session_id: str,
) -> list[str]:
    thread = state.runtime_store.get_thread_by_runtime_session_id(
        workspace_id=workspace_id,
        runtime_session_id=session_id,
    )
    if thread is None or not state.runtime_store.delete_thread(thread.thread_id):
        return []
    return [thread.thread_id]


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


def _elapsed_ms(started_at: float, finished_at: float) -> float:
    return round((finished_at - started_at) * 1000, 3)
