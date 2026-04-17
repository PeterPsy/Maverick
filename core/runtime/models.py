"""Runtime-domain models for the initial v3 scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeLocation:
    """Describe the runtime root for one workspace."""

    workspace_id: str
    path: Path
