"""Calendar JSON state loading and normalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.app_sdk.storage import read_json_state, update_json_state

from constants import SCHEMA_VERSION, STATE_FILE
from event_records import normalize_event
from view_filters import default_view_filter, normalize_view_filter


def default_state() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "events": [], "view_filter": default_view_filter()}


def normalize_state_for_storage(raw_state: dict[str, Any] | None) -> dict[str, Any]:
    """Return a persisted state document normalized to the current data schema."""
    source = raw_state if isinstance(raw_state, dict) else {}
    events = source.get("events")
    return {
        "schema_version": SCHEMA_VERSION,
        "events": [normalize_event(item) for item in events] if isinstance(events, list) else [],
        "view_filter": normalize_view_filter(source.get("view_filter")),
    }


def read_state(data_root: Path) -> dict[str, Any]:
    return normalize_state_for_storage(read_json_state(data_root, STATE_FILE, default_state()))


def update_state(data_root: Path, updater) -> None:
    update_json_state(data_root, STATE_FILE, updater, default_state())
