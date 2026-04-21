"""Workspace data helpers for SDK-generated apps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.app_sdk.errors import AppSdkPathError


def safe_app_data_path(data_root: str | Path, relative_path: str | Path) -> Path:
    """Resolve a path below one app-owned data root and reject traversal."""
    root = Path(data_root).resolve()
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise AppSdkPathError("App data paths must be relative.")
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise AppSdkPathError(f"App data path `{relative_path}` escapes `{root}`.")
    return resolved


def read_json_state(data_root: str | Path, relative_path: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read one JSON object from app-owned data storage."""
    path = safe_app_data_path(data_root, relative_path)
    if not path.exists():
        return dict(default or {})
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON state file `{path}` must contain an object.")
    return payload


def write_json_state(data_root: str | Path, relative_path: str, payload: dict[str, Any]) -> Path:
    """Write one JSON object under app-owned data storage."""
    path = safe_app_data_path(data_root, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def ensure_json_state(data_root: str | Path, relative_path: str, default: dict[str, Any]) -> Path:
    """Create one JSON state file if it does not already exist."""
    path = safe_app_data_path(data_root, relative_path)
    if not path.exists():
        write_json_state(data_root, relative_path, default)
    return path
