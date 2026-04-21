"""Persistent preferences for the Maverick Monitor app."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"
STATE_FILE = "state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "refresh_seconds": 10,
        "selected_tab": "machine",
        "updated_at": _now_iso(),
    }


def load_state(data_root: Path) -> dict[str, Any]:
    path = data_root / STATE_FILE
    if not path.is_file():
        return seed_state(data_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return seed_state(data_root)
    state = default_state()
    state.update({key: value for key, value in payload.items() if key in state})
    state["schema_version"] = SCHEMA_VERSION
    return state


def save_state(data_root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    state = load_state(data_root)
    if "refresh_seconds" in updates:
        state["refresh_seconds"] = max(5, min(int(updates["refresh_seconds"]), 300))
    if "selected_tab" in updates:
        selected = str(updates["selected_tab"] or "").strip()
        if selected in {"machine", "apps", "workspaces", "processes"}:
            state["selected_tab"] = selected
    state["updated_at"] = _now_iso()
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return state


def seed_state(data_root: Path) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    state = default_state()
    path = data_root / STATE_FILE
    if not path.exists():
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return load_state(data_root)
