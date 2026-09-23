"""Workspace-owned JSON persistence for Marta Ops."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from core.app_sdk.storage import read_json_state, update_json_state

from errors import MartaOpsError


STATE_FILE = "state.json"
SCHEMA_VERSION = "1"


def default_state() -> dict[str, Any]:
    """Return a fresh empty Marta Ops state."""
    return {
        "schema_version": SCHEMA_VERSION,
        "collaborations": [],
        "ideas": [],
    }


def normalize_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the small stable storage envelope."""
    state = dict(raw or {})
    collaborations = state.get("collaborations", [])
    ideas = state.get("ideas", [])
    if not isinstance(collaborations, list) or not isinstance(ideas, list):
        raise MartaOpsError("Lo stato di Marta Ops non è valido.", status_code=500)
    return {
        "schema_version": SCHEMA_VERSION,
        "collaborations": [dict(item) for item in collaborations if isinstance(item, dict)],
        "ideas": [dict(item) for item in ideas if isinstance(item, dict)],
    }


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
