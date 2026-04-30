"""Workspace data helpers for SDK-generated apps."""

from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

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
    with _file_lock(path, exclusive=False):
        if not path.exists():
            return dict(default or {})
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON state file `{path}` must contain an object.")
    return payload


def write_json_state(data_root: str | Path, relative_path: str, payload: dict[str, Any]) -> Path:
    """Write one JSON object under app-owned data storage."""
    path = safe_app_data_path(data_root, relative_path)
    with _file_lock(path, exclusive=True):
        _write_json_payload(path, payload)
    return path


def update_json_state(
    data_root: str | Path,
    relative_path: str,
    updater: Callable[[dict[str, Any]], dict[str, Any] | None],
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically read, mutate, and write one JSON object under app-owned data storage."""
    path = safe_app_data_path(data_root, relative_path)
    with _file_lock(path, exclusive=True):
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = dict(default or {})
        if not isinstance(payload, dict):
            raise ValueError(f"JSON state file `{path}` must contain an object.")
        next_payload = updater(payload)
        if next_payload is None:
            next_payload = payload
        if not isinstance(next_payload, dict):
            raise ValueError("JSON state updater must return an object.")
        _write_json_payload(path, next_payload)
        return next_payload


def ensure_json_state(data_root: str | Path, relative_path: str, default: dict[str, Any]) -> Path:
    """Create one JSON state file if it does not already exist."""
    path = safe_app_data_path(data_root, relative_path)
    if not path.exists():
        write_json_state(data_root, relative_path, default)
    return path


def _write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


class _file_lock:
    def __init__(self, path: Path, *, exclusive: bool) -> None:
        self.path = path
        self.exclusive = exclusive
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._handle = lock_path.open("a+")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
