"""Calendar reference entity search, resolve, and summarize operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from operations import get_event, list_events
from reference_records import reference_record
from request_inputs import validate_reference_entity_type
from scalars import string_list


def reference_search(
    data_root: Path,
    *,
    app_id: str = "calendar",
    entity_type: str = "event",
    query: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Search event references."""
    validate_reference_entity_type(entity_type)
    query_text = query.strip().lower()
    results: list[dict[str, Any]] = []
    for event in list_events(data_root):
        haystack = " ".join(
            [
                str(event.get("title") or ""),
                str(event.get("description") or ""),
                str(event.get("category") or ""),
                " ".join(string_list(event.get("attendees"))),
                " ".join(string_list(event.get("tags"))),
            ]
        ).lower()
        if query_text and query_text not in haystack:
            continue
        results.append(reference_record(event, app_id=app_id))
        if len(results) >= limit:
            break
    return {"action": "references.search", "entity_type": "event", "results": results}


def reference_resolve(data_root: Path, entity_id: str, *, app_id: str = "calendar") -> dict[str, Any]:
    """Resolve one event reference."""
    event = get_event(data_root, entity_id)
    if event is None:
        return _missing_reference("references.resolve", entity_id, app_id=app_id)
    reference = reference_record(event, app_id=app_id)
    return {"action": "references.resolve", "exists": True, **reference, "reference": reference, "event": event}


def reference_summarize(data_root: Path, entity_id: str, *, app_id: str = "calendar") -> dict[str, Any]:
    """Summarize one event reference."""
    event = get_event(data_root, entity_id)
    if event is None:
        return _missing_reference("references.summarize", entity_id, app_id=app_id)
    reference = reference_record(event, app_id=app_id)
    return {
        "action": "references.summarize",
        "app_id": app_id,
        "entity_type": "event",
        "entity_id": entity_id,
        "exists": True,
        "title": reference["title"],
        "summary": reference["summary"],
        "safe_fields": reference["safe_fields"],
        "app_page": reference["app_page"],
        "deep_link": reference["deep_link"],
    }


def _missing_reference(action: str, entity_id: str, *, app_id: str) -> dict[str, Any]:
    return {
        "action": action,
        "app_id": app_id,
        "entity_type": "event",
        "entity_id": entity_id,
        "exists": False,
        "title": entity_id,
        "summary": "",
        "safe_fields": {},
    }
