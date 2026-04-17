"""App-domain storage entrypoints for canonical app locations."""

from __future__ import annotations

from pathlib import Path

from core.apps.models import AppLocation
from core.apps.paths import installed_app_root


def installed_app_location(app_id: str, start_path: Path | None = None) -> AppLocation:
    """Return the canonical location of one platform-installed app."""
    return AppLocation(app_id=app_id, path=installed_app_root(app_id=app_id, start_path=start_path))
