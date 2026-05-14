"""Publish core runtime thread catalog changes from runtime lifecycle events."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from core.runtime.runtime_threads import (
    create_runtime_thread,
    ensure_runtime_threads_for_sessions,
    find_runtime_thread_by_session,
    mark_runtime_thread_response_completed,
    mark_runtime_thread_user_message,
    runtime_thread_availability_for_session,
    thread_payload,
    update_runtime_thread_availability,
)
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.thread_titles import runtime_thread_title_for_session

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.runtime.runtime_thread import RuntimeThreadRecord


def publish_runtime_thread_catalog_change(
    state: PlatformState,
    *,
    workspace_id: str,
    action: str,
    thread: RuntimeThreadRecord | None = None,
) -> None:
    thread_bus = getattr(state, "runtime_thread_event_bus", None)
    if thread_bus is None:
        return
    threads = ensure_runtime_threads_for_sessions(
        state.runtime_store,
        workspace_id=workspace_id,
        sessions=state.runtime_store.list_sessions(workspace_id),
        title_for_session=lambda session: _thread_title_for_session(state, session),
    )
    payload = {
        "action": action,
        "threads": [thread_payload(item) for item in threads],
    }
    if thread is not None:
        latest_thread = next((item for item in threads if item.thread_id == thread.thread_id), thread)
        payload["thread"] = thread_payload(latest_thread)
        payload["thread_id"] = latest_thread.thread_id
    thread_bus.publish(workspace_id=workspace_id, event=payload)


def mark_thread_user_message_queued(
    state: PlatformState,
    *,
    workspace_id: str,
    runtime_session_id: str,
    input_text: object = "",
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    _ensure_thread_for_runtime_session(
        state,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
        now=now,
    )
    thread = mark_runtime_thread_user_message(
        state.runtime_store,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
        now=now,
    )
    publish_runtime_thread_catalog_change(
        state,
        workspace_id=workspace_id,
        action="updated",
        thread=thread,
    )
    return thread


def set_thread_availability(
    state: PlatformState,
    *,
    workspace_id: str,
    runtime_session_id: str,
    availability: str,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    if availability not in {"free", "queued", "active"}:
        raise ValueError(f"Unsupported runtime thread availability `{availability}`.")
    _ensure_thread_for_runtime_session(
        state,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        now=now,
    )
    canonical_availability = runtime_thread_availability_for_session(state.runtime_store, runtime_session_id=runtime_session_id)
    thread = update_runtime_thread_availability(
        state.runtime_store,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        availability=canonical_availability,
        now=now,
    )
    publish_runtime_thread_catalog_change(
        state,
        workspace_id=workspace_id,
        action="updated",
        thread=thread,
    )
    return thread


def mark_thread_response_completed(
    state: PlatformState,
    *,
    workspace_id: str,
    runtime_session_id: str,
    turn_id: str,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    _ensure_thread_for_runtime_session(
        state,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        now=now,
    )
    thread = mark_runtime_thread_response_completed(
        state.runtime_store,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        turn_id=turn_id,
        now=now,
    )
    publish_runtime_thread_catalog_change(
        state,
        workspace_id=workspace_id,
        action="updated",
        thread=thread,
    )
    return thread


def _ensure_thread_for_runtime_session(
    state: PlatformState,
    *,
    workspace_id: str,
    runtime_session_id: str,
    input_text: object = "",
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    existing = find_runtime_thread_by_session(
        state.runtime_store,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
    )
    if existing is not None:
        return existing
    try:
        session = state.runtime_store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return None
    if session.workspace_id != workspace_id:
        return None
    return create_runtime_thread(
        state.runtime_store,
        workspace_id=workspace_id,
        thread_id=session.session_id,
        runtime_session_id=session.session_id,
        title=_thread_title_for_session(
            state,
            session,
            input_text=input_text,
            attachments=attachments,
            app_references=app_references,
        ),
        agent_label=session.agent_id,
        agent_type_id=getattr(session, "agent_type_id", ""),
        agent_role_id=getattr(session, "agent_role_id", ""),
        source_app_id=session.source_app_id or session.agent_id,
        system_prompt=session.system_prompt or "",
        now=now or session.started_at or session.updated_at,
    )


def _thread_title_for_session(
    state: PlatformState,
    session,
    *,
    input_text: object = "",
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
) -> str:
    return runtime_thread_title_for_session(
        state.runtime_store,
        session,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
    )
