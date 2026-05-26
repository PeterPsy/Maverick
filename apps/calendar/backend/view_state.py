"""Calendar persisted view-state operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from constants import MAX_CATEGORY_LENGTH, MAX_LIST_ITEM_LENGTH, MAX_TITLE_LENGTH, SCHEMA_VERSION
from operations import list_events
from reference_records import event_deep_link
from scalars import clean_string, optional_bool, string_list
from store import read_state, update_state
from time_values import optional_time_string
from view_filters import default_view_filter, event_ids_from_body, normalize_view_filter


def read_view_filter(data_root: Path) -> dict[str, Any]:
    """Read the persisted Calendar view filter."""
    return normalize_view_filter(read_state(data_root).get("view_filter"))


def set_view_filter(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Persist a standard view filter for Calendar's reference-aware view surface."""
    preserve_custom = optional_bool(body.get("preserve_custom") or body.get("preserveCustom"), default=False)
    current = read_view_filter(data_root) if preserve_custom else default_view_filter()
    preserving_custom_view = preserve_custom and current.get("mode") == "custom"
    view_state = normalize_view_filter(
        {
            **current,
            "mode": "custom" if preserving_custom_view else "filter",
            "query": str(body.get("query") or "").strip(),
            "start_after": optional_time_string(body.get("start_after") or body.get("startAfter"), "start_after"),
            "end_before": optional_time_string(body.get("end_before") or body.get("endBefore"), "end_before"),
            "category": clean_string(body.get("category"), "category", max_length=MAX_CATEGORY_LENGTH),
            "attendee": clean_string(body.get("attendee"), "attendee", max_length=MAX_LIST_ITEM_LENGTH),
            "tags": string_list(body.get("tags")),
            "conflicts_only": optional_bool(body.get("conflicts_only") or body.get("conflictsOnly"), default=False),
            "entity_ids": current.get("entity_ids", []) if preserving_custom_view else [],
            "references": current.get("references", []) if preserving_custom_view else [],
            "title": current.get("title", "") if preserving_custom_view else "",
        }
    )
    _write_view_filter(data_root, view_state)
    return view_state


def set_custom_view(data_root: Path, body: dict[str, Any], *, app_id: str = "calendar") -> dict[str, Any]:
    """Persist a curated set of event references for Calendar's standard view surface."""
    entity_ids = event_ids_from_body(body)
    existing_ids = {event["id"] for event in list_events(data_root, profile="compact", include_description=False)}
    missing_ids = [entity_id for entity_id in entity_ids if entity_id not in existing_ids]
    if missing_ids:
        if len(missing_ids) == 1:
            raise ValueError(f"Calendar event reference `{missing_ids[0]}` was not found.")
        raise ValueError(f"Calendar event references `{', '.join(missing_ids)}` were not found.")
    view_state = normalize_view_filter(
        {
            "mode": "custom",
            "title": clean_string(body.get("title") or "Custom Calendar View", "title", max_length=MAX_TITLE_LENGTH),
            "query": str(body.get("query") or "").strip(),
            "entity_ids": entity_ids,
            "references": [
                {
                    "app_id": app_id,
                    "entity_type": "event",
                    "entity_id": entity_id,
                    "app_page": f"events/{entity_id}",
                    "deep_link": event_deep_link(app_id, entity_id),
                }
                for entity_id in entity_ids
            ],
        }
    )
    _write_view_filter(data_root, view_state)
    return view_state


def clear_custom_view(data_root: Path) -> dict[str, Any]:
    """Reset Calendar's view state."""
    view_state = default_view_filter()
    _write_view_filter(data_root, view_state)
    return view_state


def _write_view_filter(data_root: Path, view_filter: dict[str, Any]) -> None:
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        state["schema_version"] = SCHEMA_VERSION
        if not isinstance(state.get("events"), list):
            state["events"] = []
        state["view_filter"] = normalize_view_filter(view_filter)
        return state

    update_state(data_root, updater)
