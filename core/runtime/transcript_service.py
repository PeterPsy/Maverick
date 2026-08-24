"""Authorized runtime transcript read service facade."""

from __future__ import annotations

from typing import Any

from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError
from core.runtime.continuation_lineage import runtime_session_lineage
from core.runtime.store import RuntimeStore
from core.runtime.transcript_access import resolve_authorized_transcript_thread
from core.runtime.transcript_audit import record_runtime_transcript_audit
from core.runtime.transcript_catalog import list_runtime_transcript_threads
from core.runtime.transcript_history import read_runtime_event_history, read_runtime_turn_history
from core.runtime.transcript_models import (
    RuntimeEventHistoryRead,
    RuntimeTranscriptProjection,
    RuntimeTranscriptReadContext,
    RuntimeTurnHistoryRead,
)
from core.runtime.transcript_payloads import (
    TRANSCRIPT_CONTENT_TRUST,
    bounded_int,
    message_page,
    message_payload,
)
from core.runtime.transcript_projection import project_runtime_transcript
from core.runtime.transcript_safety import redact_transcript_text
from core.runtime.transcript_snapshot import (
    RuntimeTranscriptSnapshot,
    decode_runtime_transcript_snapshot,
    encode_runtime_transcript_snapshot,
)


__all__ = [
    "list_runtime_transcript_threads",
    "read_runtime_event_history",
    "read_runtime_transcript",
    "read_runtime_transcript_message",
]


DEFAULT_TRANSCRIPT_LIMIT = 30
MAX_TRANSCRIPT_LIMIT = 50
TRANSCRIPT_EMBEDDED_CONTENT_CHARS = 2_000
DEFAULT_MESSAGE_WINDOW_CHARS = 12_000
MAX_MESSAGE_WINDOW_CHARS = 12_000


def read_runtime_transcript(
    store: RuntimeStore,
    *,
    context: RuntimeTranscriptReadContext,
    thread_id: str,
    limit: int = DEFAULT_TRANSCRIPT_LIMIT,
    before_cursor: str | None = None,
    snapshot_cursor: str | None = None,
    profile: str = "messages",
    observability_store=None,
    surface: str = "service",
) -> dict[str, Any]:
    """Read one bounded page of visible messages from complete event history."""
    normalized_profile = str(profile or "messages").strip()
    if normalized_profile != "messages":
        raise RuntimeTranscriptValidationError("unsupported_transcript_profile")
    bounded_limit = bounded_int(limit, minimum=1, maximum=MAX_TRANSCRIPT_LIMIT, field="limit")
    try:
        thread, session, relation = resolve_authorized_transcript_thread(
            store,
            context=context,
            thread_id=thread_id,
        )
    except RuntimeTranscriptAccessError as error:
        _audit_denied_read(
            observability_store,
            action="core.runtime.transcript.read",
            surface=surface,
            context=context,
            thread_id=thread_id,
            profile=normalized_profile,
            limit=bounded_limit,
            reason=error.reason,
        )
        raise
    history, turn_history, projection, resolved_snapshot_cursor = _snapshot_projection(
        store,
        session_id=session.session_id,
        snapshot_cursor=snapshot_cursor,
    )
    messages, page = message_page(
        projection.messages,
        limit=bounded_limit,
        before_cursor=before_cursor,
    )
    payload_messages = [message_payload(message, max_chars=TRANSCRIPT_EMBEDDED_CONTENT_CHARS) for message in messages]
    warnings = [*history.warnings, *turn_history.warnings, *projection.warnings]
    if not page["cursor_found"]:
        warnings.append("message_cursor_not_found")
    redactions_applied = any(bool(message["redactions_applied"]) for message in payload_messages)
    complete = history.complete and turn_history.complete and projection.complete and bool(page["cursor_found"])
    record_runtime_transcript_audit(
        observability_store,
        action="core.runtime.transcript.read",
        surface=surface,
        context=context,
        outcome="authorized",
        target_thread_id=thread.thread_id,
        authorization_relation=relation,
        profile=normalized_profile,
        page_limit=bounded_limit,
        returned_count=len(payload_messages),
        redactions_applied=redactions_applied,
        extra={"has_more_before": page["has_more_before"], "projection_complete": complete},
    )
    return {
        "thread_id": thread.thread_id,
        "profile": normalized_profile,
        "content_trust": TRANSCRIPT_CONTENT_TRUST,
        "messages": payload_messages,
        "page": page,
        "snapshot_cursor": resolved_snapshot_cursor,
        "projection_complete": complete,
        "projection_warnings": warnings,
        "redactions_applied": redactions_applied,
    }


def read_runtime_transcript_message(
    store: RuntimeStore,
    *,
    context: RuntimeTranscriptReadContext,
    thread_id: str,
    message_id: str,
    offset: int = 0,
    max_chars: int = DEFAULT_MESSAGE_WINDOW_CHARS,
    snapshot_cursor: str | None = None,
    observability_store=None,
    surface: str = "service",
) -> dict[str, Any]:
    """Read an explicit character window from one projected message."""
    bounded_offset = bounded_int(offset, minimum=0, maximum=2_147_483_647, field="offset")
    bounded_max_chars = bounded_int(max_chars, minimum=1, maximum=MAX_MESSAGE_WINDOW_CHARS, field="max_chars")
    try:
        thread, session, relation = resolve_authorized_transcript_thread(
            store,
            context=context,
            thread_id=thread_id,
        )
    except RuntimeTranscriptAccessError as error:
        _audit_denied_read(
            observability_store,
            action="core.runtime.transcript.message.read",
            surface=surface,
            context=context,
            thread_id=thread_id,
            profile="message",
            limit=bounded_max_chars,
            reason=error.reason,
        )
        raise
    history, turn_history, projection, resolved_snapshot_cursor = _snapshot_projection(
        store,
        session_id=session.session_id,
        snapshot_cursor=snapshot_cursor,
    )
    message = next((item for item in projection.messages if item.message_id == message_id), None)
    if message is None:
        error = RuntimeTranscriptAccessError("transcript_message_not_found", status_code=404)
        _audit_denied_read(
            observability_store,
            action="core.runtime.transcript.message.read",
            surface=surface,
            context=context,
            thread_id=thread.thread_id,
            profile="message",
            limit=bounded_max_chars,
            reason=error.reason,
            authorization_relation=relation,
        )
        raise error
    safe_content = redact_transcript_text(message.content)
    redactions_applied = message.redactions_applied or safe_content != message.content
    content_char_count = len(safe_content)
    start = min(bounded_offset, content_char_count)
    range_end = min(content_char_count, start + bounded_max_chars)
    content = safe_content[start:range_end]
    has_more = range_end < content_char_count
    complete = start == 0 and not has_more
    record_runtime_transcript_audit(
        observability_store,
        action="core.runtime.transcript.message.read",
        surface=surface,
        context=context,
        outcome="authorized",
        target_thread_id=thread.thread_id,
        authorization_relation=relation,
        profile="message",
        page_limit=bounded_max_chars,
        returned_count=len(content),
        redactions_applied=redactions_applied,
        extra={"offset": start, "has_more": has_more},
    )
    return {
        "thread_id": thread.thread_id,
        "message_id": message.message_id,
        "turn_id": message.turn_id,
        "role": message.role,
        "status": message.status,
        "content": content,
        "content_char_count": content_char_count,
        "offset": start,
        "range_end": range_end,
        "has_more": has_more,
        "next_offset": range_end if has_more else None,
        "complete": complete,
        "redactions_applied": redactions_applied,
        "content_trust": TRANSCRIPT_CONTENT_TRUST,
        "snapshot_cursor": resolved_snapshot_cursor,
        "projection_complete": history.complete and turn_history.complete and projection.complete,
        "projection_warnings": [*history.warnings, *turn_history.warnings, *projection.warnings],
        "source_event_ids": message.source_event_ids,
    }


def _audit_denied_read(
    observability_store,
    *,
    action: str,
    surface: str,
    context: RuntimeTranscriptReadContext,
    thread_id: str,
    profile: str,
    limit: int,
    reason: str,
    authorization_relation: str | None = None,
) -> None:
    record_runtime_transcript_audit(
        observability_store,
        action=action,
        surface=surface,
        context=context,
        outcome=reason,
        target_thread_id=str(thread_id or "").strip() or None,
        authorization_relation=authorization_relation,
        profile=profile,
        page_limit=limit,
    )


def _snapshot_projection(
    store: RuntimeStore,
    *,
    session_id: str,
    snapshot_cursor: str | None,
) -> tuple[RuntimeEventHistoryRead, RuntimeTurnHistoryRead, RuntimeTranscriptProjection, str]:
    session = store.get_session(session_id)
    lineage = runtime_session_lineage(store, session)
    requested = (
        decode_runtime_transcript_snapshot(snapshot_cursor, session_id=session_id)
        if str(snapshot_cursor or "").strip()
        else None
    )
    current_event_history = read_runtime_event_history(
        store,
        session_id,
        snapshot_position=requested.event_position if requested else None,
        snapshot_event_id=requested.event_id if requested else None,
    )
    current_turn_history = read_runtime_turn_history(
        store,
        session_id,
        snapshot_position=requested.turn_position if requested else None,
        snapshot_turn_id=requested.turn_id if requested else None,
    )
    predecessor_event_histories = [
        read_runtime_event_history(store, predecessor.session_id)
        for predecessor in lineage[:-1]
    ]
    predecessor_turn_histories = [
        read_runtime_turn_history(store, predecessor.session_id)
        for predecessor in lineage[:-1]
    ]
    event_history = RuntimeEventHistoryRead(
        events=sorted(
            [
                event
                for history in [*predecessor_event_histories, current_event_history]
                for event in history.events
            ],
            key=lambda event: (event.created_at, event.event_id),
        ),
        snapshot_position=current_event_history.snapshot_position,
        snapshot_event_id=current_event_history.snapshot_event_id,
        warnings=[
            warning
            for history in [*predecessor_event_histories, current_event_history]
            for warning in history.warnings
        ],
        complete=all(
            history.complete
            for history in [*predecessor_event_histories, current_event_history]
        ),
    )
    turn_history = RuntimeTurnHistoryRead(
        turns=sorted(
            [
                turn
                for history in [*predecessor_turn_histories, current_turn_history]
                for turn in history.turns
            ],
            key=lambda turn: (turn.created_at, turn.turn_id),
        ),
        snapshot_position=current_turn_history.snapshot_position,
        snapshot_turn_id=current_turn_history.snapshot_turn_id,
        warnings=[
            warning
            for history in [*predecessor_turn_histories, current_turn_history]
            for warning in history.warnings
        ],
        complete=all(
            history.complete
            for history in [*predecessor_turn_histories, current_turn_history]
        ),
    )
    snapshot = requested or RuntimeTranscriptSnapshot(
        session_id=session_id,
        event_position=current_event_history.snapshot_position,
        event_id=current_event_history.snapshot_event_id,
        turn_position=current_turn_history.snapshot_position,
        turn_id=current_turn_history.snapshot_turn_id,
    )
    projection = project_runtime_transcript(
        event_history.events,
        turn_history.turns,
        include_turn_status_fallbacks=False,
        warn_on_turn_input_fallback=True,
    )
    return event_history, turn_history, projection, encode_runtime_transcript_snapshot(snapshot)
