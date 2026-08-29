"""Durable Core-owned execution fences for workspace app sidecars."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from core.apps.errors import AppHostingError
from core.apps.models import WorkspaceAppSidecarQuarantineRecord


class SidecarQuarantineError(AppHostingError):
    """A durable sidecar quarantine blocks executable app authority."""

    code = "sidecar_quarantined"
    phase = "sidecar_quarantine"


def activate_sidecar_quarantine(
    store,
    *,
    workspace_id: str,
    app_id: str,
    reason: str,
) -> WorkspaceAppSidecarQuarantineRecord:
    """Persist the fence before any best-effort process cleanup is attempted."""
    existing = store.get_workspace_app_sidecar_quarantine(
        workspace_id=workspace_id,
        app_id=app_id,
    )
    if isinstance(existing, WorkspaceAppSidecarQuarantineRecord) and existing.active:
        return existing
    now = _utc_now()
    record = WorkspaceAppSidecarQuarantineRecord(
        quarantine_id=f"sidecar-quarantine-{secrets.token_urlsafe(18)}",
        workspace_id=workspace_id,
        app_id=app_id,
        reason=reason,
        active=True,
        created_at=(
            existing.created_at
            if isinstance(existing, WorkspaceAppSidecarQuarantineRecord)
            else now
        ),
        updated_at=now,
    )
    return store.save_workspace_app_sidecar_quarantine(record)


def release_sidecar_quarantine(
    store,
    *,
    workspace_id: str,
    app_id: str,
) -> WorkspaceAppSidecarQuarantineRecord | None:
    """Release a fence explicitly without starting any process as a side effect."""
    existing = store.get_workspace_app_sidecar_quarantine(
        workspace_id=workspace_id,
        app_id=app_id,
    )
    if not isinstance(existing, WorkspaceAppSidecarQuarantineRecord):
        return None
    if not existing.active:
        return existing
    record = WorkspaceAppSidecarQuarantineRecord(
        quarantine_id=existing.quarantine_id,
        workspace_id=existing.workspace_id,
        app_id=existing.app_id,
        reason=existing.reason,
        active=False,
        created_at=existing.created_at,
        updated_at=_utc_now(),
    )
    return store.save_workspace_app_sidecar_quarantine(record)


def active_sidecar_quarantine(
    store,
    *,
    workspace_id: str,
    app_id: str,
) -> WorkspaceAppSidecarQuarantineRecord | None:
    """Return only a valid active fence; persistence failures remain fail-closed."""
    record = store.get_workspace_app_sidecar_quarantine(
        workspace_id=workspace_id,
        app_id=app_id,
    )
    if isinstance(record, WorkspaceAppSidecarQuarantineRecord) and record.active:
        return record
    return None


def require_sidecar_not_quarantined(store, *, workspace_id: str, app_id: str) -> None:
    if active_sidecar_quarantine(
        store,
        workspace_id=workspace_id,
        app_id=app_id,
    ) is not None:
        raise SidecarQuarantineError(
            f"App `{app_id}` sidecars are quarantined pending operator recovery."
        )


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "SidecarQuarantineError",
    "activate_sidecar_quarantine",
    "active_sidecar_quarantine",
    "release_sidecar_quarantine",
    "require_sidecar_not_quarantined",
]
