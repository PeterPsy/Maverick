"""Core-owned conversation thread lifecycle helpers."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Callable

from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.store import RuntimeStore


RuntimeCleanupCallback = Callable[[str, str], dict[str, object]]


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def thread_payload(thread: RuntimeThreadRecord) -> dict[str, object]:
    return asdict(thread)


def list_runtime_threads(store: RuntimeStore, *, workspace_id: str) -> list[RuntimeThreadRecord]:
    return sorted(
        store.list_threads(workspace_id),
        key=lambda thread: thread.updated_at,
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
        availability="free",
        created_at=timestamp,
        updated_at=timestamp,
    )
    return store.save_thread(thread)


def _default_thread_title(session: RuntimeSessionRecord) -> str:
    if session.agent_id.strip():
        return session.agent_id.strip()
    return "New chat"


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
        "availability": 0,
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
    return store.save_thread(replace(thread, **patch))


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
