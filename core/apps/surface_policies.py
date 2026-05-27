"""Policy helpers for app-owned executable surfaces."""

from __future__ import annotations

from core.apps.models import AppCompatibilityDescriptor


def app_requires_full_access_runtime(compatibility: AppCompatibilityDescriptor) -> bool:
    """Return whether the app contract excludes sandbox execution."""
    supported_modes = compatibility.supported_workspace_modes or []
    return "full-access" in supported_modes and "sandbox" not in supported_modes
