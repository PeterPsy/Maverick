"""Reference entity surface for CRM records."""

from __future__ import annotations

from typing import Any, Callable

from errors import ValidationError
from store import get_record, parse_limit, require_text

from .record_lifecycle import ENTITY_ROUTE_SEGMENTS, title_for_record


SearchRecords = Callable[[Any, dict[str, Any]], dict[str, Any]]


def reference_manifest() -> dict[str, Any]:
    return {
        "entity_types": [
            {"entity_type": "lead", "display_name": "Lead"},
            {"entity_type": "account", "display_name": "Account"},
            {"entity_type": "contact", "display_name": "Contact"},
            {"entity_type": "deal", "display_name": "Deal"},
            {"entity_type": "activity", "display_name": "Activity"},
            {"entity_type": "task", "display_name": "Task"},
            {"entity_type": "note", "display_name": "Note"},
        ]
    }


def reference_search(db, payload: dict[str, Any], search_records: SearchRecords) -> dict[str, Any]:
    results = search_records(
        db,
        {
            "query": require_text(payload, "query"),
            "entity_type": require_text(payload, "entity_type", default="all") or "all",
            "limit": parse_limit(payload, 20),
        },
    )["results"]
    references = []
    for item in results:
        record = item.get("record", {}) if isinstance(item.get("record"), dict) else {}
        entity_type = str(item.get("entity_type") or "")
        entity_id = str(item.get("entity_id") or record.get("id") or "")
        title = str(item.get("title") or title_for_record(record) or entity_id)
        summary = str(item.get("body") or record.get("summary") or record.get("body") or "")
        references.append(_reference(entity_type, entity_id, title, summary))
    return {"results": references}


def reference_resolve(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type, entity_id = _split_reference_payload(payload)
    record = get_record(db, entity_type, entity_id)
    return _reference(entity_type, entity_id, title_for_record(record), str(record.get("summary") or ""), exists=True, record=record)


def reference_summarize(db, payload: dict[str, Any]) -> dict[str, Any]:
    resolved = reference_resolve(db, payload)
    record = resolved.get("record", {})
    return {
        "summary": resolved.get("summary") or resolved.get("title"),
        "safe_fields": {
            "title": resolved.get("title"),
            "entity_type": resolved.get("entity_type"),
            "updated_at": record.get("updated_at") if isinstance(record, dict) else "",
        },
    }


def _split_reference_payload(payload: dict[str, Any]) -> tuple[str, str]:
    entity_type = require_text(payload, "entity_type")
    entity_id = require_text(payload, "entity_id") or require_text(payload, "id")
    if not entity_type and ":" in entity_id:
        entity_type, entity_id = entity_id.split(":", 1)
    if not entity_type or not entity_id:
        raise ValidationError("`entity_type` and `entity_id` are required.")
    return entity_type, entity_id


def _reference(entity_type: str, entity_id: str, title: str, summary: str, *, exists: bool = True, record: dict[str, Any] | None = None) -> dict[str, Any]:
    route_segment = ENTITY_ROUTE_SEGMENTS.get(entity_type, f"{entity_type}s")
    payload = {
        "app_id": "crm",
        "entity_type": entity_type,
        "entity_id": f"{entity_type}:{entity_id}",
        "title": title,
        "summary": summary,
        "exists": exists,
        "deep_link": f"/app/crm/{route_segment}/{entity_id}",
        "app_page": f"{route_segment}/{entity_id}",
    }
    if record is not None:
        payload["record"] = record
    return payload
