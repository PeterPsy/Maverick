"""Core-owned capability revocation for durable app-sidecar quarantine."""

from __future__ import annotations

from typing import Any

from core.api.sidecar_proxy import (
    quarantine_app_sidecars,
    release_app_sidecar_quarantine,
)
from core.apps.sidecar_quarantine import (
    activate_sidecar_quarantine,
    release_sidecar_quarantine,
)
from core.model_access.broker import revoke_model_access_leases


def quarantine_workspace_app_sidecars(
    state,
    *,
    workspace_id: str,
    app_id: str,
) -> dict[str, Any]:
    """Persist the fence before revoking every live Core capability."""
    state.app_store.get_workspace_app_binding(
        workspace_id=workspace_id,
        app_id=app_id,
    )
    quarantine = activate_sidecar_quarantine(
        state.app_store,
        workspace_id=workspace_id,
        app_id=app_id,
        reason="sidecar_recovery_required",
    )
    state.sidecar_browser_sessions.revoke_app(
        workspace_id=workspace_id,
        app_id=app_id,
    )
    revoked_model_lease_count = revoke_model_access_leases(
        state.repository_root,
        workspace_id=workspace_id,
        app_id=app_id,
    )
    process = quarantine_app_sidecars(
        workspace_id=workspace_id,
        app_id=app_id,
    )
    return {
        "ready": False,
        "quarantined": True,
        "persistent": True,
        "quarantine_id": quarantine.quarantine_id,
        "proxy_revoked": process.get("proxy_revoked") is True,
        "browser_sessions_revoked": True,
        "model_access_revoked": True,
        "revoked_model_lease_count": revoked_model_lease_count,
        "writer_stop_confirmed": process.get("writer_stop_confirmed") is True,
        "affected_service_count": int(process.get("affected_service_count") or 0),
    }


def release_workspace_app_sidecar_quarantine(
    state,
    *,
    workspace_id: str,
    app_id: str,
) -> dict[str, Any]:
    """Release durable state before opening the in-process startup gate."""
    state.app_store.get_workspace_app_binding(
        workspace_id=workspace_id,
        app_id=app_id,
    )
    released = release_sidecar_quarantine(
        state.app_store,
        workspace_id=workspace_id,
        app_id=app_id,
    )
    release_app_sidecar_quarantine(
        workspace_id=workspace_id,
        app_id=app_id,
    )
    return {
        "ready": False,
        "quarantined": False,
        "released": released is not None,
    }


__all__ = [
    "quarantine_workspace_app_sidecars",
    "release_workspace_app_sidecar_quarantine",
]
