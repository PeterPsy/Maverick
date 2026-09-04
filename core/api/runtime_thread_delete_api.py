"""HTTP-facing runtime thread deletion and batch mutation helpers."""

from __future__ import annotations

from core.api.http import StartResponse, json_response
from core.api.platform_state import PlatformState
from core.api.runtime_cleanup_batch import cleanup_runtime_sessions_batch
from core.api.session_api import RequestSession
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_runtime_session_operation
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_session import RuntimeSessionRecord, runtime_session_allows_user_thread
from core.runtime.runtime_thread import RuntimeThreadRecord


RUNTIME_THREAD_DELETE_BATCH_MAX = 500


def thread_cleanup_forbidden_reason(
    state: PlatformState,
    context: RequestSession,
    *,
    runtime_session_id: str,
) -> str | None:
    if not runtime_session_id:
        return None
    try:
        session = state.runtime_store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return None
    except ValueError:
        return "runtime_thread_not_found"
    return _runtime_session_cleanup_forbidden_reason(state, context, session=session)


def _runtime_session_cleanup_forbidden_reason(
    state: PlatformState,
    context: RequestSession,
    *,
    session: RuntimeSessionRecord,
) -> str | None:
    if session.workspace_id != context.workspace_id:
        return "runtime_thread_not_found"
    try:
        require_runtime_session_operation(
            workspace_store=state.workspace_store,
            user=context.user,
            session=session,
            operation="cleanup",
        )
    except AuthorizationError as error:
        return error.reason
    return None


def delete_runtime_threads(
    state: PlatformState,
    context: RequestSession,
    *,
    threads: list[RuntimeThreadRecord],
    reason: str,
    start_path,
    action: str,
) -> dict[str, object]:
    deleted_thread_ids = [thread.thread_id for thread in threads]
    deleted_runtime_session_ids = list(
        dict.fromkeys(thread.runtime_session_id for thread in threads if thread.runtime_session_id)
    )
    runtime_cleanup = (
        cleanup_runtime_sessions_batch(
            state,
            session_ids=deleted_runtime_session_ids,
            workspace_id=context.workspace_id,
            reason=reason,
            start_path=start_path,
            delete_threads=False,
        )
        if deleted_runtime_session_ids
        else None
    )
    state.runtime_store.delete_threads(
        workspace_id=context.workspace_id,
        thread_ids=deleted_thread_ids,
    )
    if deleted_thread_ids:
        state.runtime_thread_event_bus.publish(
            workspace_id=context.workspace_id,
            event={
                "action": action,
                "deleted_thread_ids": deleted_thread_ids,
                "deleted_runtime_session_ids": deleted_runtime_session_ids,
            },
        )
    payload: dict[str, object] = {
        "deleted_thread_ids": deleted_thread_ids,
        "deleted_runtime_session_ids": deleted_runtime_session_ids,
        "action": action,
        "page_hint": {"sort": "recency_desc"},
    }
    if runtime_cleanup is not None:
        payload["runtime_cleanup_batch"] = runtime_cleanup
    return payload


def handle_thread_delete_batch(
    state: PlatformState,
    context: RequestSession,
    method: str,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
):
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    raw_thread_ids = body.get("thread_ids")
    if not isinstance(raw_thread_ids, list) or not raw_thread_ids:
        return json_response(start_response, {"error": "runtime_thread_ids_required"}, status="400 Bad Request")
    if len(raw_thread_ids) > RUNTIME_THREAD_DELETE_BATCH_MAX:
        return json_response(
            start_response,
            {
                "error": "runtime_thread_delete_batch_too_large",
                "maximum": RUNTIME_THREAD_DELETE_BATCH_MAX,
            },
            status="400 Bad Request",
        )
    thread_ids: list[str] = []
    for item in raw_thread_ids:
        if not isinstance(item, str) or not item.strip():
            return json_response(start_response, {"error": "runtime_thread_ids_invalid"}, status="400 Bad Request")
        thread_id = item.strip()
        if thread_id not in thread_ids:
            thread_ids.append(thread_id)

    catalog_threads_by_id = {
        thread.thread_id: thread
        for thread in state.runtime_store.list_threads(context.workspace_id)
    }
    threads_by_id: dict[str, RuntimeThreadRecord] = {}
    results_by_id: dict[str, dict[str, object]] = {}
    for thread_id in thread_ids:
        thread = catalog_threads_by_id.get(thread_id)
        if thread is None:
            results_by_id[thread_id] = {"thread_id": thread_id, "status": "not_found"}
            continue
        runtime_session_id = thread.runtime_session_id.strip()
        try:
            session = state.runtime_store.get_session(runtime_session_id) if runtime_session_id else None
        except RuntimeSessionNotFoundError:
            session = None
        except ValueError:
            results_by_id[thread_id] = {"thread_id": thread_id, "status": "not_found"}
            continue
        if session is not None and not runtime_session_allows_user_thread(session):
            results_by_id[thread_id] = {"thread_id": thread_id, "status": "not_found"}
            continue
        forbidden_reason = (
            _runtime_session_cleanup_forbidden_reason(state, context, session=session)
            if session is not None
            else None
        )
        if forbidden_reason == "runtime_thread_not_found":
            results_by_id[thread_id] = {"thread_id": thread_id, "status": "not_found"}
            continue
        if forbidden_reason is not None:
            return json_response(start_response, {"error": forbidden_reason}, status="403 Forbidden")
        threads_by_id[thread_id] = thread

    reason = str(body.get("reason") or "runtime_threads_deleted").strip()
    deleted_threads = [threads_by_id[thread_id] for thread_id in thread_ids if thread_id in threads_by_id]
    payload = delete_runtime_threads(
        state,
        context,
        threads=deleted_threads,
        reason=reason,
        start_path=start_path,
        action="deleted",
    )
    for thread in deleted_threads:
        results_by_id[thread.thread_id] = {
            "thread_id": thread.thread_id,
            "runtime_session_id": thread.runtime_session_id,
            "status": "deleted",
        }
    payload["results"] = [results_by_id[thread_id] for thread_id in thread_ids]
    return json_response(start_response, payload)


def _thread_references_hidden_session(state: PlatformState, thread: RuntimeThreadRecord) -> bool:
    runtime_session_id = thread.runtime_session_id.strip()
    if not runtime_session_id:
        return False
    try:
        session = state.runtime_store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return False
    except ValueError:
        return True
    return not runtime_session_allows_user_thread(session)
