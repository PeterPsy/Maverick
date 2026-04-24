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
        "view_filter": default_view_filter(),
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
    state["view_filter"] = normalize_view_filter(state.get("view_filter"))
    return state


def save_state(data_root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    state = load_state(data_root)
    if "refresh_seconds" in updates:
        state["refresh_seconds"] = max(5, min(int(updates["refresh_seconds"]), 300))
    if "selected_tab" in updates:
        selected = str(updates["selected_tab"] or "").strip()
        if selected in {"machine", "apps", "workspaces", "processes"}:
            state["selected_tab"] = selected
            state["view_filter"] = normalize_view_filter(state.get("view_filter")) | {"selected_tab": selected}
    state["updated_at"] = _now_iso()
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return state


def default_view_filter() -> dict[str, Any]:
    return {
        "mode": "search",
        "query": "",
        "selected_tab": "machine",
        "refs": [],
        "updated_at": None,
    }


def normalize_view_filter(value: object) -> dict[str, Any]:
    current = value if isinstance(value, dict) else {}
    normalized = default_view_filter()
    if str(current.get("mode") or "") == "custom":
        normalized["mode"] = "custom"
        normalized["title"] = str(current.get("title") or "Custom view")
        refs = current.get("refs")
        normalized["refs"] = refs if isinstance(refs, list) else []
    normalized["query"] = str(current.get("query") or "").strip()
    selected_tab = str(current.get("selected_tab") or "machine").strip()
    if selected_tab in {"machine", "apps", "workspaces", "processes"}:
        normalized["selected_tab"] = selected_tab
    updated_at = current.get("updated_at")
    normalized["updated_at"] = updated_at if isinstance(updated_at, str) else None
    return normalized


def set_view_filter(data_root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    state = load_state(data_root)
    view_filter = normalize_view_filter(state.get("view_filter"))
    if not bool(updates.get("preserve_custom")) or view_filter.get("mode") != "custom":
        view_filter = default_view_filter()
    view_filter["query"] = str(updates.get("query") or "").strip()
    selected_tab = str(updates.get("selected_tab") or state.get("selected_tab") or "machine").strip()
    if selected_tab in {"machine", "apps", "workspaces", "processes"}:
        view_filter["selected_tab"] = selected_tab
        state["selected_tab"] = selected_tab
    view_filter["updated_at"] = _now_iso()
    state["view_filter"] = view_filter
    state["updated_at"] = _now_iso()
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return state


def set_custom_view(data_root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    state = load_state(data_root)
    refs = updates.get("refs")
    state["view_filter"] = {
        "mode": "custom",
        "query": "",
        "selected_tab": state.get("selected_tab", "machine"),
        "title": str(updates.get("title") or "Custom view"),
        "refs": refs if isinstance(refs, list) else [],
        "updated_at": _now_iso(),
    }
    state["updated_at"] = _now_iso()
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return state


def clear_custom_view(data_root: Path) -> dict[str, Any]:
    state = load_state(data_root)
    state["view_filter"] = default_view_filter() | {"updated_at": _now_iso()}
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
