"""App-owned workspace data metadata helpers."""

from __future__ import annotations

import json
from pathlib import Path

from core.apps.models import AppDataStateRecord


APP_DATA_STATE_FILENAME = ".maverick-app.json"


def app_data_state_path(data_root: Path) -> Path:
    """Return the metadata file path for one app-owned data root."""
    return data_root / APP_DATA_STATE_FILENAME


def read_app_data_state(data_root: Path) -> AppDataStateRecord | None:
    """Read the current app-owned data metadata if it exists."""
    state_path = app_data_state_path(data_root)
    if not state_path.is_file():
        return None
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return AppDataStateRecord(**payload)


def write_app_data_state(data_root: Path, state: AppDataStateRecord) -> Path:
    """Persist the current app-owned data metadata into the data root."""
    data_root.mkdir(parents=True, exist_ok=True)
    state_path = app_data_state_path(data_root)
    state_path.write_text(json.dumps(state.__dict__, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state_path
