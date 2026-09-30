"""Workspace-owned JSON persistence for Marta Ops."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from core.app_sdk.storage import read_json_state, update_json_state

from errors import MartaOpsError


STATE_FILE = "state.json"
SCHEMA_VERSION = "2"


def default_state() -> dict[str, Any]:
    """Return a fresh empty Marta Ops state."""
    return {
        "schema_version": SCHEMA_VERSION,
        "collaborations": [],
        "ideas": [],
        "contacts": [],
        "tasks": [],
        "activity": [],
    }


def normalize_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the small stable storage envelope."""
    state = dict(raw or {})
    normalized = {**state, "schema_version": SCHEMA_VERSION}
    for key in ("collaborations", "ideas", "contacts", "tasks", "activity"):
        items = state.get(key, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise MartaOpsError("Lo stato di Marta Ops non è valido.", status_code=500)
        normalized[key] = [dict(item) for item in items]
    for index, item in enumerate(normalized["collaborations"]):
        item.setdefault("contact_id", "")
        item.setdefault("pipeline_order", index)
    return normalized


def load_state(data_root: Path) -> dict[str, Any]:
    """Load a defensive copy of workspace state."""
    return deepcopy(normalize_state(read_json_state(data_root, STATE_FILE, default_state())))


def mutate_state(
    data_root: Path,
    mutator: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomically mutate state and return the updated state plus action result."""
    result: dict[str, Any] = {}

    def apply(raw: dict[str, Any]) -> dict[str, Any]:
        state = normalize_state(raw)
        result.update(mutator(state) or {})
        return state

    state = update_json_state(data_root, STATE_FILE, apply, default=default_state())
    return deepcopy(normalize_state(state)), deepcopy(result)
