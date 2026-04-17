"""Runtime-domain service entrypoints for the initial v3 scaffold."""

from __future__ import annotations

from pathlib import Path

from core.runtime.models import RuntimeLocation
from core.runtime.store import runtime_location


def resolve_runtime(workspace_id: str, start_path: Path | None = None) -> RuntimeLocation:
    """Resolve the runtime root for one workspace through the runtime service layer."""
    return runtime_location(workspace_id=workspace_id, start_path=start_path)
