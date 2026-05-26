"""Calendar surface action names and normalization."""

from __future__ import annotations

from typing import Any


ACTION_ALIASES = {
    "manifest": "operations.manifest",
    "help": "operations.manifest",
    "events.list": "list",
    "events.create": "create",
    "events.update": "update",
    "events.delete": "delete",
    "events.move": "move",
    "availability.check": "check_availability",
    "availability.find_free_time": "find_free_time",
}

ALLOWED_ACTIONS = [
    "operations.manifest",
    "describe",
    "status",
    "list",
    "create",
    "update",
    "delete",
    "move",
    "check_availability",
    "find_free_time",
    "view_filter",
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
    "references.manifest",
    "references.search",
    "references.resolve",
    "references.summarize",
]

EXPECTED_FIELDS_BY_ACTION = {
    "create": ["title", "startTime", "endTime"],
    "update": ["id", "expected_revision"],
    "delete": ["id", "expected_revision"],
    "move": ["id", "expected_revision", "startTime or move_strategy=first_free with start_after and end_before"],
    "check_availability": ["startTime", "endTime"],
    "find_free_time": ["start_after", "end_before"],
    "set_custom_view": ["entity_ids"],
    "references.resolve": ["entity_id"],
    "references.summarize": ["entity_id"],
}


def normalize_action(value: Any) -> str:
    """Return a canonical Calendar action name."""
    action = str(value or "operations.manifest").strip().lower()
    return ACTION_ALIASES.get(action, action)
