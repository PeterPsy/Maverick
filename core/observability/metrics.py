"""Metrics recording helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.observability.models import MetricKind, MetricRecord
from core.observability.store import ObservabilityStore


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def record_metric(
    store: ObservabilityStore,
    *,
    metric_name: str,
    kind: MetricKind,
    value: float,
    tags: dict[str, str] | None = None,
    workspace_id: str | None = None,
    app_id: str | None = None,
    runtime_session_id: str | None = None,
    provider_id: str | None = None,
    now: datetime | None = None,
) -> MetricRecord:
    """Persist one metric sample."""
    record = MetricRecord(
        metric_id=str(uuid4()),
        metric_name=metric_name,
        kind=kind,
        value=float(value),
        workspace_id=workspace_id,
        app_id=app_id,
        runtime_session_id=runtime_session_id,
        provider_id=provider_id,
        tags=dict(tags or {}),
        recorded_at=now or utcnow(),
    )
    return store.save_metric(record)
