"""Structured event emission helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.observability.models import EventPlane, StructuredEventRecord
from core.observability.redaction import redact_payload
from core.observability.store import ObservabilityStore


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def emit_structured_event(
    store: ObservabilityStore,
    *,
    event_type: str,
    event_plane: EventPlane,
    source_domain: str,
    payload: dict,
    workspace_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    runtime_session_id: str | None = None,
    turn_id: str | None = None,
    provider_id: str | None = None,
    now: datetime | None = None,
) -> StructuredEventRecord:
    """Persist one redacted structured event."""
    record = StructuredEventRecord(
        event_id=str(uuid4()),
        event_type=event_type,
        event_plane=event_plane,
        source_domain=source_domain,
        workspace_id=workspace_id,
        app_id=app_id,
        run_id=run_id,
        runtime_session_id=runtime_session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        payload=redact_payload(payload),
        occurred_at=now or utcnow(),
    )
    return store.save_event(record)
