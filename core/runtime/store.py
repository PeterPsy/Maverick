"""Runtime-domain storage entrypoints for workspace runtime roots."""

from __future__ import annotations

from pathlib import Path

from core.runtime.models import RuntimeLocation
from core.runtime.paths import workspace_runtime_root


def runtime_location(workspace_id: str, start_path: Path | None = None) -> RuntimeLocation:
    """Return the canonical runtime location for one workspace."""
    return RuntimeLocation(
        workspace_id=workspace_id,
        path=workspace_runtime_root(workspace_id=workspace_id, start_path=start_path),
    )
