"""Batch orchestration for complete runtime-session cleanup."""

from __future__ import annotations

import logging
import time

from core.api.platform_state import PlatformState
from core.api.runtime_cleanup import _delete_runtime_root, cleanup_runtime_session
from core.api.runtime_cleanup_errors import RuntimeCleanupError
from core.api.runtime_cleanup_hooks import cleanup_app_runtime_session_metadata
from core.inter_agent.service import (
    InterAgentService,
    RUNTIME_CHILD_EXECUTION_MODE,
    TERMINAL_RUN_STATUSES,
)
from core.inter_agent.surfaces import inter_agent_payload
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.paths import runtime_session_root


logger = logging.getLogger(__name__)


def cleanup_runtime_sessions_batch(
    state: PlatformState,
    *,
    session_ids: list[str],
    workspace_id: str,
    reason: str,
    start_path=None,
    delete_threads: bool = True,
) -> dict[str, object]:
    """Expand children once, batch app hooks, then clean every session exactly once."""
    started_at = time.perf_counter()
    repository_root = start_path or state.repository_root
    root_session_ids = list(dict.fromkeys(item.strip() for item in session_ids if item.strip()))
    active_runs = [
        run
        for run in state.inter_agent_store.list_runs(workspace_id)
        if run.root_runtime_session_id in root_session_ids and run.status not in TERMINAL_RUN_STATUSES
    ]
    expanded_session_ids = list(root_session_ids)
    for run in active_runs:
        for participant in state.inter_agent_store.list_participants(run.run_id, workspace_id=workspace_id):
            if participant.execution_mode != RUNTIME_CHILD_EXECUTION_MODE or not participant.runtime_session_id:
                continue
            if participant.runtime_session_id not in expanded_session_ids:
                expanded_session_ids.append(participant.runtime_session_id)
    expansion_finished_at = time.perf_counter()

    existing_session_ids: list[str] = []
    runtime_roots_by_session_id = {}
    for session_id in expanded_session_ids:
        try:
            session = state.runtime_store.get_session(session_id)
        except (RuntimeSessionNotFoundError, ValueError):
            continue
        if session.workspace_id != workspace_id:
            continue
        try:
            runtime_root = runtime_session_root(
                workspace_id=session.workspace_id,
                session_id=session.session_id,
                start_path=repository_root,
            )
        except ValueError as error:
            raise RuntimeCleanupError("runtime_session_id_unsafe") from error
        existing_session_ids.append(session.session_id)
        runtime_roots_by_session_id[session.session_id] = runtime_root
    app_cleanup = cleanup_app_runtime_session_metadata(
        state,
        workspace_id=workspace_id,
        session_ids=existing_session_ids,
        start_path=repository_root,
    )
    hooks_finished_at = time.perf_counter()

    results_by_session_id: dict[str, dict[str, object]] = {}
    existing_session_id_set = set(existing_session_ids)

    def cleanup_once(session_id: str, cleanup_reason: str, *, allow_hidden: bool) -> dict[str, object]:
        existing = results_by_session_id.get(session_id)
        if existing is not None:
            return existing
        if session_id not in existing_session_id_set:
            result = _missing_session_cleanup_result(session_id)
            results_by_session_id[session_id] = result
            return result
        result = cleanup_runtime_session(
            state,
            session_id=session_id,
            reason=cleanup_reason,
            start_path=repository_root,
            publish_thread_events=False,
            allow_hidden_inter_agent_cleanup=allow_hidden,
            delete_threads=False,
            cleanup_inter_agent_runs=False,
            cleanup_app_metadata=False,
            defer_persistence_cleanup=True,
        )
        results_by_session_id[session_id] = result
        return result

    service = InterAgentService(state.inter_agent_store)
    inter_agent_cleanup: list[dict[str, object]] = []
    for run in active_runs:
        result = service.close_run(
            workspace_id=workspace_id,
            run_id=run.run_id,
            cleanup_runtime_session=lambda session_id, cleanup_reason: cleanup_once(
                session_id,
                cleanup_reason,
                allow_hidden=True,
            ),
            reason=reason,
            terminal_status="cancelled",
            delete_records=True,
        )
        inter_agent_cleanup.append(inter_agent_payload({"run_id": run.run_id, **result}))
    for session_id in expanded_session_ids:
        if session_id not in root_session_ids:
            cleanup_once(session_id, reason, allow_hidden=True)
    children_finished_at = time.perf_counter()

    for session_id in root_session_ids:
        cleanup_once(session_id, reason, allow_hidden=False)
    roots_finished_at = time.perf_counter()

    deleted_records = state.runtime_store.delete_session_records_batch(existing_session_ids)
    usage_store = getattr(state, "usage_store", None)
    if usage_store is not None:
        for session_id in existing_session_ids:
            deleted_records.setdefault(session_id, {})["usage_samples"] = usage_store.delete_session(session_id)
    records_finished_at = time.perf_counter()
    deleted_threads_by_session_id: dict[str, list[str]] = {
        session_id: [] for session_id in existing_session_ids
    }
    if delete_threads:
        linked_threads = [
            thread
            for session_id in existing_session_ids
            if (
                thread := state.runtime_store.get_thread_by_runtime_session_id(
                    workspace_id=workspace_id,
                    runtime_session_id=session_id,
                )
            )
            is not None
        ]
        state.runtime_store.delete_threads(
            workspace_id=workspace_id,
            thread_ids=[thread.thread_id for thread in linked_threads],
        )
        for thread in linked_threads:
            deleted_threads_by_session_id[thread.runtime_session_id].append(thread.thread_id)
        if linked_threads:
            state.runtime_thread_event_bus.publish(
                workspace_id=workspace_id,
                event={
                    "action": "deleted",
                    "deleted_thread_ids": [thread.thread_id for thread in linked_threads],
                    "deleted_runtime_session_ids": [thread.runtime_session_id for thread in linked_threads],
                },
            )
    threads_finished_at = time.perf_counter()
    for session_id in existing_session_ids:
        result = results_by_session_id.get(session_id)
        if result is None:
            continue
        private_payloads = result.get("deleted", {}).get("tool_private_payloads", 0)
        result["deleted"] = {
            **deleted_records.get(session_id, {}),
            "tool_private_payloads": private_payloads,
        }
        result["deleted_thread_ids"] = deleted_threads_by_session_id[session_id]
        result["deleted_threads"] = len(deleted_threads_by_session_id[session_id])
        result["runtime_root_deleted"] = _delete_runtime_root(
            runtime_roots_by_session_id[session_id],
            workspace_id=workspace_id,
            session_id=session_id,
            start_path=repository_root,
        )
    cleanup_finished_at = time.perf_counter()
    timings_ms = {
        "expand_children": _elapsed_ms(started_at, expansion_finished_at),
        "app_hooks": _elapsed_ms(expansion_finished_at, hooks_finished_at),
        "child_sessions": _elapsed_ms(hooks_finished_at, children_finished_at),
        "root_sessions": _elapsed_ms(children_finished_at, roots_finished_at),
        "record_deletion": _elapsed_ms(roots_finished_at, records_finished_at),
        "thread_catalog": _elapsed_ms(records_finished_at, threads_finished_at),
        "filesystem": _elapsed_ms(threads_finished_at, cleanup_finished_at),
        "total": _elapsed_ms(started_at, cleanup_finished_at),
    }
    logger.info(
        "runtime cleanup batch complete workspace_id=%s root_sessions=%d expanded_sessions=%d app_hooks=%d "
        "expand_ms=%.3f app_hooks_ms=%.3f child_sessions_ms=%.3f root_sessions_ms=%.3f "
        "records_ms=%.3f thread_catalog_ms=%.3f filesystem_ms=%.3f total_ms=%.3f",
        workspace_id,
        len(root_session_ids),
        len(expanded_session_ids),
        len(app_cleanup),
        timings_ms["expand_children"],
        timings_ms["app_hooks"],
        timings_ms["child_sessions"],
        timings_ms["root_sessions"],
        timings_ms["record_deletion"],
        timings_ms["thread_catalog"],
        timings_ms["filesystem"],
        timings_ms["total"],
    )
    return {
        "requested_session_ids": root_session_ids,
        "expanded_session_ids": expanded_session_ids,
        "session_results": [results_by_session_id[item] for item in expanded_session_ids if item in results_by_session_id],
        "inter_agent_cleanup": inter_agent_cleanup,
        "app_cleanup": app_cleanup,
        "timings_ms": timings_ms,
    }


def _elapsed_ms(started_at: float, finished_at: float) -> float:
    return round((finished_at - started_at) * 1000, 3)


def _missing_session_cleanup_result(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "found": False,
        "workspace_id": None,
        "terminated_processes": 0,
        "cancelled_turns": 0,
        "deleted": {},
        "deleted_threads": 0,
        "deleted_thread_ids": [],
        "runtime_root_deleted": False,
    }
