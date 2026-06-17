"""Canonical path helpers for workspace runtime roots."""

from __future__ import annotations

from pathlib import Path
import re

from core.workspaces.paths import workspace_paths

SAFE_RUNTIME_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def workspace_runtime_root(workspace_id: str, start_path: Path | None = None) -> Path:
    """Return the runtime root for one workspace."""
    return workspace_paths(workspace_id=workspace_id, start_path=start_path).runtime


def normalize_runtime_session_id(session_id: str) -> str:
    """Return a runtime session id that is safe to use as one path segment."""
    normalized = str(session_id or "").strip()
    if not SAFE_RUNTIME_SESSION_ID_PATTERN.fullmatch(normalized):
        raise ValueError("runtime_session_id_unsafe")
    return normalized


def runtime_session_root(workspace_id: str, session_id: str, start_path: Path | None = None) -> Path:
    """Return the provider/runtime state root for one runtime session."""
    return workspace_runtime_root(workspace_id=workspace_id, start_path=start_path) / "sessions" / normalize_runtime_session_id(session_id)
