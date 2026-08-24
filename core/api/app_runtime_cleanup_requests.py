"""Apply runtime cleanup requests returned by app entrypoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.app_runtime_cleanup_commit import apply_runtime_cleanup_commit
from core.api.platform_state import PlatformState
from core.apps.errors import AppHostingError
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_runtime_session_operation
from core.identity.models import UserRecord
from core.runtime.errors import RuntimeSessionNotFoundError, RuntimeThreadNotFoundError
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.runtime_threads import thread_payload


def apply_runtime_cleanup_requests(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    cleanup_allowed: bool,
    user: UserRecord | None,
    source_root: Path,
    backend_entrypoint: str | None,
    data_root: str,
    parsed,
    result: dict[str, Any],
    start_path: Path,
) -> list[dict[str, object]]:
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    requests = result.pop("runtime_cleanup_requests", None)
    if requests is None and response_json is not None:
        requests = response_json.pop("runtime_cleanup_requests", [])
    if requests is None:
        requests = []
    if not isinstance(requests, list) or not requests:
        return []
    if not cleanup_allowed:
        raise AppHostingError(f"App `{app_id}` requested runtime cleanup without declaring runtime.cleanup_sessions.")

    from core.api.runtime_cleanup_batch import cleanup_runtime_sessions_batch

    cleanup_results: list[dict[str, object]] = []
    deleted_thread_ids: list[str] = []
    deleted_runtime_session_ids: list[str] = []
    seen_thread_ids: set[str] = set()
    seen_session_ids: set[str] = set()
    for item in requests:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or f"{app_id}_runtime_cleanup")
        thread_ids = _runtime_cleanup_thread_ids_for_request(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            item=item,
        )
        if thread_ids:
            for thread_id in thread_ids:
                _authorize_runtime_thread_cleanup(
                    state,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    user=user,
                    thread_id=thread_id,
                )
            batch_threads = []
            for thread_id in thread_ids:
                if thread_id in seen_thread_ids:
                    continue
                seen_thread_ids.add(thread_id)
                try:
                    thread = state.runtime_store.get_thread(thread_id)
                except RuntimeThreadNotFoundError:
                    continue
                if thread.workspace_id != workspace_id:
                    continue
                batch_threads.append(thread)
            batch_session_ids = list(
                dict.fromkeys(thread.runtime_session_id for thread in batch_threads if thread.runtime_session_id)
            )
            if batch_session_ids:
                batch_cleanup = cleanup_runtime_sessions_batch(
                    state,
                    session_ids=batch_session_ids,
                    workspace_id=workspace_id,
                    reason=reason,
                    start_path=start_path,
                    delete_threads=False,
                )
                cleanup_results.extend(batch_cleanup["session_results"])
            state.runtime_store.delete_threads(
                workspace_id=workspace_id,
                thread_ids=[thread.thread_id for thread in batch_threads],
            )
            for thread in batch_threads:
                deleted_thread_ids.append(thread.thread_id)
                if thread.runtime_session_id and thread.runtime_session_id not in deleted_runtime_session_ids:
                    deleted_runtime_session_ids.append(thread.runtime_session_id)
                    seen_session_ids.add(thread.runtime_session_id)
            continue
        session_ids = _runtime_cleanup_session_ids_for_request(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            item=item,
        )
        for session_id in session_ids:
            _authorize_runtime_session_cleanup(
                state,
                workspace_id=workspace_id,
                app_id=app_id,
                user=user,
                session_id=session_id,
            )
        pending_session_ids = [
            session_id
            for session_id in session_ids
            if session_id not in seen_session_ids
        ]
        if pending_session_ids:
            batch_cleanup = cleanup_runtime_sessions_batch(
                state,
                session_ids=pending_session_ids,
                workspace_id=workspace_id,
                reason=reason,
                start_path=start_path,
            )
            cleanup_results.extend(batch_cleanup["session_results"])
            seen_session_ids.update(batch_cleanup["expanded_session_ids"])
    if deleted_thread_ids:
        _publish_runtime_threads_deleted(
            state,
            workspace_id=workspace_id,
            deleted_thread_ids=deleted_thread_ids,
            deleted_runtime_session_ids=deleted_runtime_session_ids,
        )
    apply_runtime_cleanup_commit(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        source_root=source_root,
        backend_entrypoint=backend_entrypoint,
        data_root=data_root,
        parsed=parsed,
        result=result,
        cleanup_results=cleanup_results,
    )
    return cleanup_results


def _runtime_cleanup_thread_ids_for_request(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    item: dict[str, Any],
) -> list[str]:
    thread_id = str(item.get("runtime_thread_id") or item.get("thread_id") or "").strip()
    if thread_id:
        try:
            thread = state.runtime_store.get_thread(thread_id)
        except RuntimeThreadNotFoundError:
            return []
        if thread.workspace_id != workspace_id:
            raise AppHostingError(f"App `{app_id}` cannot clean runtime thread outside workspace `{workspace_id}`.")
        if thread.source_app_id != app_id:
            raise AppHostingError(f"App `{app_id}` cannot clean a runtime thread owned by another source app.")
        return [thread.thread_id]

    project_id = str(item.get("project_id") or "").strip()
    if project_id:
        return [
            thread.thread_id
            for thread in state.runtime_store.list_threads(workspace_id)
            if thread.project_id == project_id and thread.source_app_id == app_id
        ]

    return []


def _runtime_cleanup_session_ids_for_request(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    item: dict[str, Any],
) -> list[str]:
    session_id = str(item.get("runtime_session_id") or item.get("session_id") or "").strip()
    if session_id:
        try:
            session = state.runtime_store.get_session(session_id)
        except (RuntimeSessionNotFoundError, ValueError):
            return [session_id]
        if session.workspace_id != workspace_id:
            raise AppHostingError(f"App `{app_id}` cannot clean runtime session outside workspace `{workspace_id}`.")
        if not runtime_session_allows_user_thread(session):
            raise AppHostingError(f"App `{app_id}` cannot clean hidden inter-agent runtime session `{session_id}`.")
        if session.source_app_id != app_id:
            raise AppHostingError(f"App `{app_id}` cannot clean a runtime session owned by another source app.")
        return [session_id]

    return []


def _authorize_runtime_thread_cleanup(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    thread_id: str,
) -> None:
    try:
        thread = state.runtime_store.get_thread(thread_id)
    except RuntimeThreadNotFoundError:
        return
    if thread.workspace_id != workspace_id:
        raise AppHostingError(f"App `{app_id}` cannot clean runtime thread outside workspace `{workspace_id}`.")
    if thread.source_app_id != app_id:
        raise AppHostingError(f"App `{app_id}` cannot clean a runtime thread owned by another source app.")
    if not thread.runtime_session_id:
        return
    _authorize_runtime_session_cleanup(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        user=user,
        session_id=thread.runtime_session_id,
    )


def _authorize_runtime_session_cleanup(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    session_id: str,
) -> None:
    try:
        session = state.runtime_store.get_session(session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return
    if session.workspace_id != workspace_id:
        raise AppHostingError(f"App `{app_id}` cannot clean runtime session outside workspace `{workspace_id}`.")
    if not runtime_session_allows_user_thread(session):
        raise AppHostingError(f"App `{app_id}` cannot clean hidden inter-agent runtime session `{session_id}`.")
    if session.source_app_id != app_id:
        raise AppHostingError(f"App `{app_id}` cannot clean a runtime session owned by another source app.")
    if user is None:
        raise AuthorizationError("runtime_session_cleanup_forbidden")
    require_runtime_session_operation(
        workspace_store=state.workspace_store,
        user=user,
        session=session,
        operation="cleanup",
    )


def _publish_runtime_threads_deleted(
    state: PlatformState,
    *,
    workspace_id: str,
    deleted_thread_ids: list[str],
    deleted_runtime_session_ids: list[str],
) -> None:
    threads = sorted(state.runtime_store.list_threads(workspace_id), key=lambda thread: thread.updated_at, reverse=True)
    state.runtime_thread_event_bus.publish(
        workspace_id=workspace_id,
        event={
            "action": "deleted",
            "threads": [thread_payload(thread) for thread in threads],
            "deleted_thread_ids": deleted_thread_ids,
            "deleted_runtime_session_ids": deleted_runtime_session_ids,
        },
    )
