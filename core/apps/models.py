"""App-domain models for the initial v3 scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppLocation:
    """Describe one canonical app location."""

    app_id: str
    path: Path
