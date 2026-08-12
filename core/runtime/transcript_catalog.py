"""Authorized metadata-only runtime transcript catalog."""

from __future__ import annotations

from typing import Any

from core.runtime.errors import RuntimeTranscriptAccessError
from core.runtime.runtime_threads import list_runtime_threads
from core.runtime.store import RuntimeStore
from core.runtime.transcript_access import transcript_authorization_relation
from core.runtime.transcript_audit import record_runtime_transcript_audit
from core.runtime.transcript_models import RuntimeTranscriptReadContext
from core.runtime.transcript_payloads import bounded_int


DEFAULT_THREAD_LIMIT = 20
MAX_THREAD_LIMIT = 100


def list_runtime_transcript_threads(
    store: RuntimeStore,
    *,
    context: RuntimeTranscriptReadContext,
    query: str | None = None,
    source_app_id: str | None = None,
    agent_type_id: str | None = None,
    project_id: str | None = None,
    limit: int = DEFAULT_THREAD_LIMIT,
    cursor: str | None = None,
    observability_store=None,
    surface: str = "service",
) -> dict[str, Any]:
    """Filter by authorization before applying query or pagination."""
    bounded_limit = bounded_int(limit, minimum=1, maximum=MAX_THREAD_LIMIT, field="limit")
    sessions = {session.session_id: session for session in store.list_sessions(context.workspace_id)}
    authorized: list[tuple[Any, Any, str]] = []
    for thread in list_runtime_threads(store, workspace_id=context.workspace_id):
        session = sessions.get(thread.runtime_session_id)
        if session is None:
            continue
        try:
            relation = transcript_authorization_relation(session, context)
        except RuntimeTranscriptAccessError:
            continue
        authorized.append((thread, session, relation))

    filters = {
        "query": str(query or "").strip().casefold(),
        "source_app_id": str(source_app_id or "").strip(),
        "agent_type_id": str(agent_type_id or "").strip(),
        "project_id": str(project_id or "").strip(),
    }
    filtered = [item for item in authorized if _thread_matches(item[0], **filters)]
    normalized_cursor = str(cursor or "").strip()
    cursor_found = not normalized_cursor
    if normalized_cursor:
        cursor_index = next(
            (index for index, (thread, _session, _relation) in enumerate(filtered) if thread.thread_id == normalized_cursor),
            None,
        )
        cursor_found = cursor_index is not None
        filtered = filtered[cursor_index + 1 :] if cursor_index is not None else []
    page_items = filtered[:bounded_limit]
    threads = [_thread_payload(thread, session) for thread, session, _relation in page_items]
    record_runtime_transcript_audit(
        observability_store,
        action="core.runtime.threads.list",
        surface=surface,
        context=context,
        outcome="authorized",
        page_limit=bounded_limit,
        returned_count=len(threads),
        extra={
            "authorization_relations": sorted({relation for _thread, _session, relation in page_items}),
            "cursor_present": bool(normalized_cursor),
            "cursor_found": cursor_found,
        },
    )
    return {
        "threads": threads,
        "page": {
            "limit": bounded_limit,
            "has_more": len(filtered) > bounded_limit,
            "next_cursor": page_items[-1][0].thread_id if len(filtered) > bounded_limit and page_items else None,
            "sort": "recency_desc",
            "cursor_found": cursor_found,
        },
    }


def _thread_payload(thread, session) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "title": thread.title,
        "source_app_id": thread.source_app_id,
        "agent_label": thread.agent_label,
        "agent_type_id": thread.agent_type_id,
        "project_id": thread.project_id,
        "session_status": session.status,
        "availability": thread.availability,
        "created_at": thread.created_at,
        "last_user_message_at": thread.last_user_message_at,
        "last_completed_response_at": thread.last_completed_response_at,
        "transcript_available": True,
    }


def _thread_matches(thread, *, query: str, source_app_id: str, agent_type_id: str, project_id: str) -> bool:
    if source_app_id and thread.source_app_id != source_app_id:
        return False
    if agent_type_id and thread.agent_type_id != agent_type_id:
        return False
    if project_id and str(thread.project_id or "") != project_id:
        return False
    if not query:
        return True
    searchable = " ".join(
        [
            thread.title,
            thread.source_app_id,
            thread.agent_label,
            thread.agent_type_id,
            thread.agent_role_id,
            str(thread.project_id or ""),
        ]
    ).casefold()
    return query in searchable
