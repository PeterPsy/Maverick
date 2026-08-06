"""Transport-safe text windows for agent-facing Storage reads."""

from __future__ import annotations

import json

from limits import MAX_TEXT_READ_PAGE_CHARS, MAX_TEXT_READ_PAGE_SERIALIZED_BYTES


def bounded_text_window(text: str, *, offset: int, max_chars: int | None) -> dict:
    """Return one deterministic page whose JSON string stays within the transport budget."""
    text_char_count = len(text)
    start = min(offset, text_char_count)
    requested_end = text_char_count if max_chars is None else min(text_char_count, start + max_chars)
    character_limited_end = min(requested_end, start + MAX_TEXT_READ_PAGE_CHARS)
    candidate = text[start:character_limited_end]
    candidate = _fit_serialized_budget(candidate)
    range_end = start + len(candidate)
    serialized_bytes = _serialized_size(candidate)
    has_more = range_end < text_char_count
    return {
        "text": candidate,
        "text_char_count": text_char_count,
        "offset": start,
        "max_chars": max_chars,
        "range_end": range_end,
        "page_char_count": len(candidate),
        "page_serialized_bytes": serialized_bytes,
        "transport_max_chars": MAX_TEXT_READ_PAGE_CHARS,
        "transport_max_serialized_bytes": MAX_TEXT_READ_PAGE_SERIALIZED_BYTES,
        "transport_limited": range_end < requested_end,
        "has_more": has_more,
        "next_offset": range_end if has_more else None,
        "complete": start == 0 and range_end == text_char_count,
    }


def _fit_serialized_budget(value: str) -> str:
    if _serialized_size(value) <= MAX_TEXT_READ_PAGE_SERIALIZED_BYTES:
        return value
    low = 0
    high = len(value)
    while low < high:
        midpoint = (low + high + 1) // 2
        if _serialized_size(value[:midpoint]) <= MAX_TEXT_READ_PAGE_SERIALIZED_BYTES:
            low = midpoint
        else:
            high = midpoint - 1
    return value[:low]


def _serialized_size(value: str) -> int:
    return len(json.dumps(value, ensure_ascii=True).encode("utf-8"))
