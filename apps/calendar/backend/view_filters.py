"""Calendar view-state model normalization."""

from __future__ import annotations

from typing import Any

from constants import (
    MAX_CATEGORY_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_LIST_ITEM_LENGTH,
    MAX_LIST_ITEMS,
    MAX_TITLE_LENGTH,
    SCHEMA_VERSION,
)
from event_records import event_ids
from scalars import clean_string, optional_bool, string_list
from time_values import optional_time_string


def default_view_filter() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "default",
        "title": "",
        "query": "",
        "start_after": "",
        "end_before": "",
        "category": "",
        "attendee": "",
        "tags": [],
        "conflicts_only": False,
        "entity_ids": [],
        "references": [],
    }


def normalize_view_filter(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return default_view_filter()
    mode = str(raw.get("mode") or "default").strip().lower()
    if mode not in {"default", "filter", "custom"}:
        mode = "default"
    entity_ids = event_ids(raw.get("entity_ids"))
    references = raw.get("references")
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "title": clean_string(raw.get("title"), "title", max_length=MAX_TITLE_LENGTH),
        "query": str(raw.get("query") or "").strip()[:MAX_DESCRIPTION_LENGTH],
        "start_after": optional_time_string(raw.get("start_after"), "start_after"),
        "end_before": optional_time_string(raw.get("end_before"), "end_before"),
        "category": clean_string(raw.get("category"), "category", max_length=MAX_CATEGORY_LENGTH),
        "attendee": clean_string(raw.get("attendee"), "attendee", max_length=MAX_LIST_ITEM_LENGTH),
        "tags": string_list(raw.get("tags")),
        "conflicts_only": optional_bool(raw.get("conflicts_only") or raw.get("conflictsOnly"), default=False),
        "entity_ids": entity_ids,
        "references": references if isinstance(references, list) else [],
    }


def event_ids_from_body(body: dict[str, Any]) -> list[str]:
    raw_ids = body.get("entity_ids") or body.get("event_ids") or body.get("ids")
    ids = event_ids(raw_ids)
    refs = body.get("references") or body.get("refs")
    if isinstance(refs, list):
        ids.extend(
            event_ids(
                [
                    item.get("entity_id") or item.get("id")
                    for item in refs
                    if isinstance(item, dict) and str(item.get("entity_type") or "event") == "event"
                ]
            )
        )
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        raise ValueError("At least one event entity id is required.")
    return unique_ids[:MAX_LIST_ITEMS]
