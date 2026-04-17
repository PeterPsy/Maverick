"""App-domain service entrypoints for the initial v3 scaffold."""

from __future__ import annotations

from pathlib import Path

from core.apps.models import AppLocation
from core.apps.store import installed_app_location


def resolve_installed_app(app_id: str, start_path: Path | None = None) -> AppLocation:
    """Resolve one platform-installed app through the app-domain service layer."""
    return installed_app_location(app_id=app_id, start_path=start_path)
