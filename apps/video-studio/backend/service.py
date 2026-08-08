"""Service logic for `video-studio`."""

from __future__ import annotations

from core.app_sdk.runtime import AppEntrypointPayload


def status_payload(payload: AppEntrypointPayload) -> dict[str, object]:
    """Return a small health/status payload for this app."""
    return {
        "app_id": "video-studio",
        "workspace_id": payload.workspace_id,
        "status": "ready",
    }
