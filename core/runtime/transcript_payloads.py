"""Bounded response payload helpers for transcript services."""

from __future__ import annotations

from typing import Any

from core.runtime.errors import RuntimeTranscriptValidationError
from core.runtime.transcript_models import RuntimeTranscriptMessage
from core.runtime.transcript_safety import redact_transcript_text


TRANSCRIPT_CONTENT_TRUST = "untrusted_conversation_data"


def message_page(messages: list[RuntimeTranscriptMessage], *, limit: int, before_cursor: str | None):
    """Return one chronological page selected from the newest matching messages."""
    normalized_cursor = str(before_cursor or "").strip()
    cursor_found = not normalized_cursor
    candidates = messages
    if normalized_cursor:
        cursor_index = next((index for index, message in enumerate(messages) if message.message_id == normalized_cursor), None)
        cursor_found = cursor_index is not None
        candidates = messages[:cursor_index] if cursor_index is not None else []
    has_more_before = len(candidates) > limit
    selected = candidates[-limit:]
    page = {
        "limit": limit,
        "has_more_before": has_more_before,
        "next_before_cursor": selected[0].message_id if has_more_before and selected else None,
        "before_cursor": normalized_cursor or None,
        "cursor_found": cursor_found,
        "sort": "chronological_asc",
    }
    return selected, page


def message_payload(message: RuntimeTranscriptMessage, *, max_chars: int) -> dict[str, Any]:
    """Build a bounded message preview with explicit continuation metadata."""
    safe_content = redact_transcript_text(message.content)
    redactions_applied = message.redactions_applied or safe_content != message.content
    content_char_count = len(safe_content)
    range_end = min(content_char_count, max_chars)
    payload = {
        "message_id": message.message_id,
        "turn_id": message.turn_id,
        "role": message.role,
        "content": safe_content[:range_end],
        "content_char_count": content_char_count,
        "content_complete": range_end == content_char_count,
        "next_offset": range_end if range_end < content_char_count else None,
        "status": message.status,
        "created_at": message.created_at,
        "source_event_ids": message.source_event_ids,
        "redactions_applied": redactions_applied,
        "content_trust": TRANSCRIPT_CONTENT_TRUST,
    }
    if message.attachments:
        payload["attachments"] = message.attachments
    if message.app_references:
        payload["app_references"] = message.app_references
    if message.structured_content is not None:
        payload["structured_content"] = message.structured_content
    return payload


def bounded_int(value: object, *, minimum: int, maximum: int, field: str) -> int:
    """Parse and clamp one integer surface argument."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise RuntimeTranscriptValidationError(f"invalid_{field}") from error
    if parsed < minimum:
        raise RuntimeTranscriptValidationError(f"invalid_{field}")
    return min(parsed, maximum)
