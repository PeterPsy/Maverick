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
    return payload if isinstance(payload, dict) else seed_state(data_root)


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
