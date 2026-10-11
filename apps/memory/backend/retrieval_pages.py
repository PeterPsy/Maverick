"""Read-only, request-bound cursors and response budgets."""

import base64
from hashlib import sha256
import json
import sqlite3

from database import normalize_limit
from errors import MemoryValidationError


def fingerprint(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]


def retrieval_revision(db: sqlite3.Connection) -> str:
    # Include queue/evidence changes as well as graph edits. No read writes state.
    return fingerprint([tuple(db.execute(f"SELECT count(*), max(updated_at) FROM {table}").fetchone())
                        for table in ("nodes", "edges", "wiki_pages", "sources", "ingest_jobs")])


def page_offset(cursor: object, binding: str) -> int:
    if not cursor:
        return 0
    try:
        if not isinstance(cursor, str) or len(cursor) > 1024:
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        offset = value["offset"]
        if value["binding"] != binding or type(offset) is not int or not 0 <= offset <= 1_000_000:
            raise ValueError()
        return offset
    except (ValueError, TypeError, KeyError):
        raise MemoryValidationError("Invalid or stale cursor; restart with the same retrieval parameters.") from None


def page_cursor(offset: int, binding: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"offset": offset, "binding": binding}, separators=(",", ":")).encode()).decode().rstrip("=")


def response_budget(value: object, *, default: int = 9500) -> int:
    return normalize_limit(value, default=default, minimum=2000, maximum=64000, field_name="max_bytes")


def byte_count(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode())


def bounded_page(items: list[dict], *, key: str, base: dict, limit: int, offset: int,
                 binding: str, max_bytes: int) -> dict:
    selected = items[:limit]
    while True:
        has_more = len(items) > len(selected)
        payload = {**base, key: selected, "has_more": has_more,
                   "next_cursor": page_cursor(offset + len(selected), binding) if has_more else None,
                   "omitted_for_budget": min(limit, len(items)) - len(selected),
                   "stop_reason": "budget" if len(selected) < min(limit, len(items)) else "limit" if has_more else "end"}
        if byte_count(payload) <= max_bytes:
            return payload
        if not selected:
            raise MemoryValidationError("max_bytes is too small for the response metadata.")
        if len(selected) == 1:
            raise MemoryValidationError("max_bytes is too small for one result; increase the budget or request cards.")
        selected.pop()
