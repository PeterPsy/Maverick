"""Core-owned conversation thread lifecycle helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Callable
from uuid import uuid4

from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.store import RuntimeStore
from core.runtime.thread_titles import (
    DEFAULT_THREAD_TITLE,
    runtime_thread_title_for_user_message,
)


RuntimeCleanupCallback = Callable[[str, str], dict[str, object]]


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def thread_payload(thread: RuntimeThreadRecord, *, viewer_user_id: str | None = None) -> dict[str, object]:
    payload = asdict(thread)
    payload.pop("completed_response_read_at_by_user_id", None)
    payload["has_unread_completed_response"] = runtime_thread_has_unread_completed_response(
        thread,
        viewer_user_id=viewer_user_id,
    )
    return payload


def thread_recency_key(thread: RuntimeThreadRecord) -> tuple[bool, datetime, datetime, str]:
    user_message_at = thread.last_user_message_at
    return (
        user_message_at is not None,
        user_message_at or thread.created_at,
        thread.created_at,
        thread.thread_id,
    )


def list_runtime_threads(store: RuntimeStore, *, workspace_id: str) -> list[RuntimeThreadRecord]:
    threads = [
        reconcile_runtime_thread_availability(store, workspace_id=workspace_id, thread=thread)
        for thread in store.list_threads(workspace_id)
    ]
    return sorted(
        threads,
        key=thread_recency_key,
        reverse=True,
    )


def ensure_runtime_threads_for_sessions(
    store: RuntimeStore,
    *,
    workspace_id: str,
    sessions: list[RuntimeSessionRecord],
    title_for_session: Callable[[RuntimeSessionRecord], str] | None = None,
) -> list[RuntimeThreadRecord]:
    """Ensure every runtime session in a workspace has exactly one thread."""
    threads = store.list_threads(workspace_id)
    by_session_id = {thread.runtime_session_id: thread for thread in threads if thread.runtime_session_id}
    for session in sessions:
        if session.workspace_id != workspace_id or session.session_id in by_session_id:
            continue
        thread = create_runtime_thread(
            store,
            workspace_id=workspace_id,
            thread_id=session.session_id,
            runtime_session_id=session.session_id,
            title=title_for_session(session) if title_for_session else _default_thread_title(session),
            agent_label=session.agent_id,
            source_app_id=session.source_app_id or session.agent_id,
            system_prompt=session.system_prompt or "",
            now=session.started_at or session.updated_at,
        )
        by_session_id[session.session_id] = thread
    return list_runtime_threads(store, workspace_id=workspace_id)


def create_runtime_thread(
    store: RuntimeStore,
    *,
    workspace_id: str,
    thread_id: str | None = None,
    runtime_session_id: str = "",
    title: str = "",
    agent_label: str = "",
    agent_type_id: str = "",
    agent_role_id: str = "",
    source_app_id: str = "",
    system_prompt: str = "",
    project_id: str | None = None,
    now: datetime | None = None,
) -> RuntimeThreadRecord:
    normalized_session_id = runtime_session_id.strip()
    if not normalized_session_id:
        raise ValueError("runtime_session_id is required")
    timestamp = now or utcnow()
    existing = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=normalized_session_id)
    if existing is not None:
        patch: dict[str, object] = {"updated_at": timestamp}
        latest_user_message_at = runtime_thread_last_user_message_at_for_session(store, runtime_session_id=normalized_session_id)
        latest_completed_response = runtime_thread_last_completed_response_for_session(store, runtime_session_id=normalized_session_id)
        if latest_user_message_at is not None and (existing.last_user_message_at is None or existing.last_user_message_at < latest_user_message_at):
            patch["last_user_message_at"] = latest_user_message_at
        if latest_completed_response is not None:
            latest_completed_turn_id, latest_completed_at = latest_completed_response
            if existing.last_completed_response_at is None or existing.last_completed_response_at < latest_completed_at:
                patch["last_completed_response_at"] = latest_completed_at
                patch["last_completed_turn_id"] = latest_completed_turn_id
        if title.strip():
            patch["title"] = title.strip()[:80]
        if agent_label.strip():
            patch["agent_label"] = agent_label.strip()[:120]
        if agent_type_id.strip():
            patch["agent_type_id"] = agent_type_id.strip()[:120]
        if agent_role_id.strip():
            patch["agent_role_id"] = agent_role_id.strip()[:120]
        if source_app_id.strip():
            patch["source_app_id"] = source_app_id.strip()[:80]
        if system_prompt.strip():
            patch["system_prompt"] = system_prompt.strip()
        if isinstance(project_id, str) and project_id.strip():
            patch["project_id"] = project_id.strip()
        if len(patch) == 1:
            return existing
        return store.save_thread(replace(existing, **patch))
    latest_completed_response = runtime_thread_last_completed_response_for_session(store, runtime_session_id=normalized_session_id)
    thread = RuntimeThreadRecord(
        thread_id=thread_id or normalized_session_id or str(uuid4()),
        workspace_id=workspace_id,
        runtime_session_id=normalized_session_id,
        title=(title.strip() or "New chat")[:80],
        agent_label=agent_label.strip()[:120],
        agent_type_id=agent_type_id.strip()[:120],
        agent_role_id=agent_role_id.strip()[:120],
        source_app_id=source_app_id.strip()[:80],
        system_prompt=system_prompt.strip(),
        project_id=project_id.strip() if isinstance(project_id, str) and project_id.strip() else None,
        archived=False,
        availability=runtime_thread_availability_for_session(store, runtime_session_id=normalized_session_id),
        created_at=timestamp,
        updated_at=timestamp,
        last_user_message_at=runtime_thread_last_user_message_at_for_session(store, runtime_session_id=normalized_session_id),
        last_completed_response_at=latest_completed_response[1] if latest_completed_response is not None else None,
        last_completed_turn_id=latest_completed_response[0] if latest_completed_response is not None else None,
    )
    return store.save_thread(thread)


def _default_thread_title(session: RuntimeSessionRecord) -> str:
    if session.agent_id.strip():
        return session.agent_id.strip()
    return DEFAULT_THREAD_TITLE


def find_runtime_thread_by_session(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
) -> RuntimeThreadRecord | None:
    normalized_session_id = runtime_session_id.strip()
    if not normalized_session_id:
        return None
    for thread in store.list_threads(workspace_id):
        if thread.runtime_session_id == normalized_session_id:
            return thread
    return None


def update_runtime_thread(
    store: RuntimeStore,
    *,
    thread_id: str,
    workspace_id: str,
    updates: dict[str, object],
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = store.get_thread(thread_id)
    if thread.workspace_id != workspace_id:
        return None
    patch: dict[str, object] = {"updated_at": now or utcnow()}
    if "title" in updates:
        title = str(updates.get("title") or "").strip()
        if title:
            patch["title"] = title[:80]
    for key, limit in {
        "runtime_session_id": 0,
        "agent_label": 120,
        "agent_type_id": 120,
        "agent_role_id": 120,
        "source_app_id": 80,
        "system_prompt": 0,
    }.items():
        if key not in updates:
            continue
        value = str(updates.get(key) or "").strip()
        patch[key] = value[:limit] if limit else value
    if "project_id" in updates:
        project_id = str(updates.get("project_id") or "").strip()
        patch["project_id"] = project_id or None
    if "archived" in updates:
        patch["archived"] = bool(updates.get("archived"))
    if len(patch) == 1:
        return thread
    return store.save_thread(replace(thread, **patch))


def reconcile_runtime_thread_availability(
    store: RuntimeStore,
    *,
    workspace_id: str,
    thread: RuntimeThreadRecord,
    now: datetime | None = None,
) -> RuntimeThreadRecord:
    if thread.workspace_id != workspace_id or not thread.runtime_session_id:
        return thread
    expected_availability = runtime_thread_availability_for_session(store, runtime_session_id=thread.runtime_session_id)
    expected_last_user_message_at = runtime_thread_last_user_message_at_for_session(store, runtime_session_id=thread.runtime_session_id)
    expected_completed_response = runtime_thread_last_completed_response_for_session(store, runtime_session_id=thread.runtime_session_id)
    patch: dict[str, object] = {}
    if thread.availability != expected_availability:
        patch["availability"] = expected_availability
    if expected_last_user_message_at is not None and (
        thread.last_user_message_at is None or thread.last_user_message_at < expected_last_user_message_at
    ):
        patch["last_user_message_at"] = expected_last_user_message_at
    if expected_completed_response is not None:
        expected_completed_turn_id, expected_completed_at = expected_completed_response
        if thread.last_completed_response_at is None or thread.last_completed_response_at < expected_completed_at:
            patch["last_completed_response_at"] = expected_completed_at
            patch["last_completed_turn_id"] = expected_completed_turn_id
    if thread.title.strip() == DEFAULT_THREAD_TITLE:
        expected_title = runtime_thread_title_for_user_message(store, thread.runtime_session_id)
        if expected_title != DEFAULT_THREAD_TITLE and expected_title != thread.title:
            patch["title"] = expected_title
    if not patch:
        return thread
    patch["updated_at"] = now or utcnow()
    return store.save_thread(replace(thread, **patch))


def runtime_thread_availability_for_session(store: RuntimeStore, *, runtime_session_id: str) -> str:
    statuses = {turn.status for turn in store.list_turns(runtime_session_id)}
    if "active" in statuses:
        return "active"
    if "queued" in statuses:
        return "queued"
    return "free"


def runtime_thread_last_user_message_at_for_session(store: RuntimeStore, *, runtime_session_id: str) -> datetime | None:
    turns = store.list_turns(runtime_session_id)
    if not turns:
        return None
    return max(turn.created_at for turn in turns)


def runtime_thread_last_completed_response_for_session(store: RuntimeStore, *, runtime_session_id: str) -> tuple[str, datetime] | None:
    completed_turns = [turn for turn in store.list_turns(runtime_session_id) if turn.status == "completed"]
    if not completed_turns:
        return None
    latest = max(completed_turns, key=lambda turn: turn.completed_at or turn.updated_at)
    return latest.turn_id, latest.completed_at or latest.updated_at


def mark_runtime_thread_user_message(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
    input_text: object = "",
    attachments: Iterable[Mapping[str, object]] | None = None,
    app_references: Iterable[Mapping[str, object]] | None = None,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=runtime_session_id)
    if thread is None:
        return None
    timestamp = now or utcnow()
    patch: dict[str, object] = {
        "availability": runtime_thread_availability_for_session(store, runtime_session_id=runtime_session_id),
        "last_user_message_at": timestamp,
        "updated_at": timestamp,
    }
    if thread.title.strip() == DEFAULT_THREAD_TITLE:
        title = runtime_thread_title_for_user_message(
            store,
            runtime_session_id,
            input_text=input_text,
            attachments=attachments,
            app_references=app_references,
        )
        if title != DEFAULT_THREAD_TITLE and title != thread.title:
            patch["title"] = title
    return store.save_thread(replace(thread, **patch))


def mark_runtime_thread_response_completed(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
    turn_id: str,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=runtime_session_id)
    if thread is None:
        return None
    timestamp = now or utcnow()
    patch: dict[str, object] = {
        "availability": runtime_thread_availability_for_session(store, runtime_session_id=runtime_session_id),
        "updated_at": timestamp,
    }
    if thread.last_completed_response_at is None or thread.last_completed_response_at <= timestamp:
        patch["last_completed_response_at"] = timestamp
        patch["last_completed_turn_id"] = turn_id
    return store.save_thread(replace(thread, **patch))


def mark_runtime_thread_completed_response_read(
    store: RuntimeStore,
    *,
    thread_id: str,
    workspace_id: str,
    user_id: str,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")
    thread = store.get_thread(thread_id)
    if thread.workspace_id != workspace_id:
        return None
    timestamp = now or utcnow()
    receipts = dict(thread.completed_response_read_at_by_user_id or {})
    if receipts.get(normalized_user_id) == timestamp:
        return thread
    receipts[normalized_user_id] = timestamp
    return store.save_thread(
        replace(
            thread,
            completed_response_read_at_by_user_id=receipts,
            updated_at=timestamp,
        )
    )


def runtime_thread_has_unread_completed_response(thread: RuntimeThreadRecord, *, viewer_user_id: str | None) -> bool:
    normalized_user_id = str(viewer_user_id or "").strip()
    if not normalized_user_id or thread.last_completed_response_at is None:
        return False
    read_at = (thread.completed_response_read_at_by_user_id or {}).get(normalized_user_id)
    return read_at is None or read_at < thread.last_completed_response_at


def update_runtime_thread_availability(
    store: RuntimeStore,
    *,
    workspace_id: str,
    runtime_session_id: str,
    availability: str,
    now: datetime | None = None,
) -> RuntimeThreadRecord | None:
    thread = find_runtime_thread_by_session(store, workspace_id=workspace_id, runtime_session_id=runtime_session_id)
    if thread is None:
        return None
    value = _normalized_thread_availability(availability)
    if not value or thread.availability == value:
        return thread
    timestamp = now or utcnow()
    return store.save_thread(replace(thread, availability=value, updated_at=timestamp))


def _normalized_thread_availability(value: str) -> str:
    normalized = value.strip()
    if normalized not in {"free", "queued", "active"}:
        raise ValueError(f"Unsupported runtime thread availability `{normalized}`.")
    return normalized


def delete_runtime_thread_complete(
    store: RuntimeStore,
    *,
    thread_id: str,
    workspace_id: str,
    cleanup_runtime: RuntimeCleanupCallback,
    reason: str = "runtime_thread_deleted",
) -> tuple[RuntimeThreadRecord | None, dict[str, object] | None]:
    thread = store.get_thread(thread_id)
    if thread.workspace_id != workspace_id:
        return None, None
    cleanup = cleanup_runtime(thread.runtime_session_id, reason) if thread.runtime_session_id else None
    store.delete_thread(thread.thread_id)
    return thread, cleanup


def clear_runtime_threads_complete(
    store: RuntimeStore,
    *,
    workspace_id: str,
    cleanup_runtime: RuntimeCleanupCallback,
    reason: str = "runtime_threads_cleared",
) -> tuple[list[RuntimeThreadRecord], list[dict[str, object]]]:
    threads = list_runtime_threads(store, workspace_id=workspace_id)
    cleanups: list[dict[str, object]] = []
    for thread in threads:
        if thread.runtime_session_id:
            cleanups.append(cleanup_runtime(thread.runtime_session_id, reason))
        store.delete_thread(thread.thread_id)
    return threads, cleanups
