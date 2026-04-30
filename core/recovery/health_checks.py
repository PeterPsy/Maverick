"""Health probe helpers for runtime, provider, and app targets."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.apps.service import probe_workspace_app_health
from core.apps.store import AppStore
from core.providers.provider_registry import ProviderRegistry
from core.recovery.models import HealthCheckResult
from core.runtime.runtime_session import RuntimeSessionRecord


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def run_runtime_health_check(session: RuntimeSessionRecord, *, now: datetime | None = None) -> HealthCheckResult:
    """Evaluate one runtime session's health."""
    if session.status == "running":
        status = "healthy"
        detail = "Runtime session is running."
    elif session.status in {"created", "stopping"}:
        status = "degraded"
        detail = f"Runtime session is `{session.status}`."
    else:
        status = "unhealthy"
        detail = f"Runtime session is `{session.status}`."
    return HealthCheckResult(
        check_id=str(uuid4()),
        workspace_id=session.workspace_id,
        session_id=session.session_id,
        target_kind="runtime",
        target_id=session.session_id,
        status=status,
        detail=detail,
        checked_at=now or utcnow(),
    )


def run_provider_health_check(
    provider_registry: ProviderRegistry,
    *,
    provider_id: str,
    workspace_id: str | None = None,
    now: datetime | None = None,
) -> HealthCheckResult:
    """Validate one provider adapter and report the result as a health record."""
    try:
        provider_registry.get_runtime_adapter(provider_id).validate_backend()
        status = "healthy"
        detail = "Provider backend validation succeeded."
    except Exception as exc:  # pragma: no cover - exercised via tests with fake adapters
        status = "unhealthy"
        detail = str(exc)
    return HealthCheckResult(
        check_id=str(uuid4()),
        workspace_id=workspace_id,
        session_id=None,
        target_kind="provider",
        target_id=provider_id,
        status=status,
        detail=detail,
        checked_at=now or utcnow(),
    )


def run_app_health_check(
    *,
    app_store: AppStore,
    workspace_id: str,
    app_id: str,
    start_path=None,
    now: datetime | None = None,
) -> HealthCheckResult:
    """Run one real app health probe through the app contract."""
    is_healthy, detail = probe_workspace_app_health(
        app_store,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
    )
    return HealthCheckResult(
        check_id=str(uuid4()),
        workspace_id=workspace_id,
        session_id=None,
        target_kind="app",
        target_id=app_id,
        status="healthy" if is_healthy else "unhealthy",
        detail=detail or ("App health check passed." if is_healthy else "App health check failed."),
        checked_at=now or utcnow(),
    )
