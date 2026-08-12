"""Generic workspace-app sidecar restart capability."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from core.api.sidecar_proxy import restart_declared_app_sidecars
from core.apps.errors import AppLifecycleError
from core.apps.models import WorkspaceAppBindingRecord
from core.apps.store import AppStore
from core.apps.surfaces import resolve_workspace_app_surface
from core.observability.service import record_platform_audit, record_platform_event


RUNTIME_CHANGED_EVENT = "maverick.app.runtime-changed"


def app_supports_sidecar_restart(
    store: AppStore,
    *,
    binding: WorkspaceAppBindingRecord,
    start_path: Path | None = None,
) -> bool:
    """Return whether an enabled binding declares at least one governed sidecar."""
    if binding.status != "enabled":
        return False
    try:
        _source_root, parsed = resolve_workspace_app_surface(
            store,
            binding=binding,
            start_path=start_path,
        )
    except Exception:
        return False
    return bool(parsed.contract.services.http_sidecars)


def restart_workspace_app_sidecars(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    sidecar_browser_sessions,
    start_path: Path,
    app_event_bus=None,
    observability_store=None,
    runtime_session_id: str | None = None,
    shutdown_controller=None,
) -> dict[str, Any]:
    """Revoke one app's browser authority, restart only its sidecars, and publish remount state."""
    started_at = time.monotonic()
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    if binding.status != "enabled":
        raise AppLifecycleError(
            f"App `{app_id}` must be enabled in workspace `{workspace_id}` before sidecar restart."
        )
    source_root, parsed = resolve_workspace_app_surface(
        store,
        binding=binding,
        start_path=start_path,
    )
    sidecars = tuple(parsed.contract.services.http_sidecars)
    if not sidecars:
        raise AppLifecycleError(f"App `{app_id}` does not declare HTTP sidecars.")

    sidecar_browser_sessions.revoke_app(workspace_id=workspace_id, app_id=app_id)
    try:
        readiness = restart_declared_app_sidecars(
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=source_root,
            data_root=binding.data_root,
            sidecars=sidecars,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
    except Exception as error:
        _audit_restart(
            observability_store,
            workspace_id=workspace_id,
            app_id=app_id,
            runtime_session_id=runtime_session_id,
            status="failed",
            payload={
                "declared_service_count": len(sidecars),
                "error_code": type(error).__name__,
            },
        )
        raise AppLifecycleError(
            f"App `{app_id}` sidecar restart failed: {type(error).__name__}."
        ) from error

    duration = round(time.monotonic() - started_at, 6)
    event = {
        "type": RUNTIME_CHANGED_EVENT,
        "workspace_id": workspace_id,
        "owner_app_id": app_id,
        "resource": "runtime/frontend",
        "reason": "sidecars_restarted",
    }
    if app_event_bus is not None:
        app_event_bus.publish(event)
    payload = {
        "declared_service_count": len(sidecars),
        "ready": True,
        "service_count": readiness.get("service_count", 0),
        "stopped_service_count": readiness.get("stopped_service_count", 0),
    }
    _audit_restart(
        observability_store,
        workspace_id=workspace_id,
        app_id=app_id,
        runtime_session_id=runtime_session_id,
        status="succeeded",
        payload=payload,
    )
    if observability_store is not None:
        record_platform_event(
            observability_store,
            event_type="app.sidecars.restarted",
            event_plane="workspace",
            source_domain="apps.sidecars",
            workspace_id=workspace_id,
            app_id=app_id,
            payload=payload,
        )
    return {
        "status": "ready",
        "workspace_id": workspace_id,
        "app_id": app_id,
        "browser_sessions_revoked": True,
        "duration_seconds": duration,
        "readiness": readiness,
        "event": event,
    }


def _audit_restart(
    observability_store,
    *,
    workspace_id: str,
    app_id: str,
    runtime_session_id: str | None,
    status: str,
    payload: dict[str, object],
) -> None:
    if observability_store is None:
        return
    record_platform_audit(
        observability_store,
        action=f"app.{app_id}.sidecars.restart",
        status=status,
        source_domain="apps.sidecars",
        detail=f"Sidecar restart for app `{app_id}` {status}.",
        workspace_id=workspace_id,
        app_id=app_id,
        runtime_session_id=runtime_session_id,
        payload=payload,
    )
