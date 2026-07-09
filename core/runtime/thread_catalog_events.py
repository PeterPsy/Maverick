"""Publish core runtime thread catalog changes from runtime lifecycle events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.runtime.runtime_threads import (
    create_runtime_thread,
    find_runtime_thread_by_session,
    mark_runtime_thread_response_completed,
    mark_runtime_thread_user_message,
    runtime_thread_availability_for_session,
    thread_summary_payload,
    update_runtime_thread_availability,
)
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE, derive_thread_title, runtime_thread_title_for_session

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
    payload = {
        "action": action,
    }
    if thread is not None:
        payload["thread"] = thread_summary_payload(thread)
        payload["thread_id"] = thread.thread_id
    thread_bus.publish(workspace_id=workspace_id, event=payload)


def mark_thread_user_message_queued(
    state: PlatformState,
    *,
    workspace_id: str,
    runtime_session_id: str,
    input_text: object = "",
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    title_generation_input_hash: str = "",
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    timestamp = now or datetime.now(tz=UTC)
    _ensure_thread_for_runtime_session(
        state,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
        title_generation_input_hash=title_generation_input_hash,
        turn_facts_known=True,
        availability="queued",
        last_user_message_at=timestamp,
        now=timestamp,
    )
    thread = mark_runtime_thread_user_message(
        state.runtime_store,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
        title_generation_input_hash=title_generation_input_hash,
        availability="queued",
        now=timestamp,
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
    canonical_availability = availability
    current_availability = runtime_thread_availability_for_session(state.runtime_store, runtime_session_id=runtime_session_id)
    if availability == "free" and current_availability != "free":
        canonical_availability = current_availability
    elif availability == "queued" and current_availability == "active":
        canonical_availability = current_availability
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
    timestamp = now or datetime.now(tz=UTC)
    _ensure_thread_for_runtime_session(
        state,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        turn_facts_known=True,
        availability="free",
        last_completed_response=(turn_id, timestamp),
        now=timestamp,
    )
    thread = mark_runtime_thread_response_completed(
        state.runtime_store,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        turn_id=turn_id,
        availability="free",
        now=timestamp,
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
    title_generation_input_hash: str = "",
    turn_facts_known: bool = False,
    availability: str | None = None,
    last_user_message_at: datetime | None = None,
    last_completed_response: tuple[str, datetime] | None = None,
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
    except ValueError:
        return None
    if session.workspace_id != workspace_id:
        return None
    if not runtime_session_allows_user_thread(session):
        return None
    pending_hash = title_generation_input_hash.strip()
    title = _runtime_thread_title_for_catalog_event(
        state,
        session,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
        pending_hash=pending_hash,
        turn_facts_known=turn_facts_known,
    )
    return create_runtime_thread(
        state.runtime_store,
        workspace_id=workspace_id,
        thread_id=session.session_id,
        runtime_session_id=session.session_id,
        title=title,
        title_pending=bool(pending_hash),
        title_source="pending" if pending_hash else "",
        title_generation_input_hash=pending_hash,
        turn_facts_known=turn_facts_known,
        availability=availability,
        last_user_message_at=last_user_message_at,
        last_completed_response=last_completed_response,
        agent_label=session.agent_id,
        agent_type_id=getattr(session, "agent_type_id", ""),
        agent_role_id=getattr(session, "agent_role_id", ""),
        source_app_id=session.source_app_id or session.agent_id,
        system_prompt=session.system_prompt or "",
        project_id=getattr(session, "project_id", None),
        now=now or session.started_at or session.updated_at,
    )


def _runtime_thread_title_for_catalog_event(
    state: PlatformState,
    session,
    *,
    input_text: object,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
    pending_hash: str,
    turn_facts_known: bool,
) -> str:
    if pending_hash:
        return DEFAULT_THREAD_TITLE
    if turn_facts_known:
        title = derive_thread_title(input_text, attachments=attachments, app_references=app_references)
        if title != DEFAULT_THREAD_TITLE:
            return title
        return str(session.agent_id or "").strip()[:80] or DEFAULT_THREAD_TITLE
    return runtime_thread_title_for_session(
        state.runtime_store,
        session,
        input_text=input_text,
        attachments=attachments,
        app_references=app_references,
    )
