"""Workspace data store for the app-store app."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


STATE_FILENAME = "state.json"
SCHEMA_VERSION = "1"


def utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_url": "https://maverick-app-store.versy.ai",
        "pinned_apps": ["chat"],
        "recent_installs": [],
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }


def state_path(data_root: Path) -> Path:
    return data_root / STATE_FILENAME


def load_state(data_root: Path) -> dict[str, Any]:
    path = state_path(data_root)
    if not path.exists():
        return seed_state(data_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return seed_state(data_root)
    payload.setdefault("pinned_apps", ["chat"])
    return payload


def save_state(data_root: Path, state: dict[str, Any]) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    state["schema_version"] = SCHEMA_VERSION
    state["updated_at"] = utcnow()
    state_path(data_root).write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return state


def seed_state(data_root: Path) -> dict[str, Any]:
    state = default_state()
    return save_state(data_root, state)


def remember_install(data_root: Path, *, app_id: str, version: str, workspace_ids: list[str]) -> dict[str, Any]:
    state = load_state(data_root)
    installs = state.setdefault("recent_installs", [])
    if not isinstance(installs, list):
        installs = []
        state["recent_installs"] = installs
    installs.insert(
        0,
        {
            "app_id": app_id,
            "version": version,
            "workspace_ids": workspace_ids,
            "installed_at": utcnow(),
        },
    )
    state["recent_installs"] = installs[:20]
    return save_state(data_root, state)


def pinned_apps(data_root: Path) -> list[str]:
    pinned = load_state(data_root).get("pinned_apps", [])
    if not isinstance(pinned, list):
        return []
    return [item for item in pinned if isinstance(item, str) and item.strip()]


def set_pinned_apps(data_root: Path, app_ids: list[str]) -> dict[str, Any]:
    state = load_state(data_root)
    unique_ids = []
    for app_id in app_ids:
        normalized = app_id.strip()
        if normalized and normalized not in unique_ids:
            unique_ids.append(normalized)
    state["pinned_apps"] = unique_ids
    return save_state(data_root, state)


def toggle_pinned_app(data_root: Path, app_id: str) -> dict[str, Any]:
    current = pinned_apps(data_root)
    if app_id in current:
        return set_pinned_apps(data_root, [item for item in current if item != app_id])
    return set_pinned_apps(data_root, [*current, app_id])
