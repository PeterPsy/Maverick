"""Audit recording helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.observability.models import AuditRecord, AuditStatus
from core.observability.redaction import redact_payload
from core.observability.store import ObservabilityStore


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def record_audit_event(
    store: ObservabilityStore,
    *,
    action: str,
    status: AuditStatus,
    source_domain: str,
    detail: str,
    payload: dict,
    workspace_id: str | None = None,
    app_id: str | None = None,
    runtime_session_id: str | None = None,
    provider_id: str | None = None,
    now: datetime | None = None,
) -> AuditRecord:
    """Persist one redacted audit record."""
    record = AuditRecord(
        audit_id=str(uuid4()),
        action=action,
        status=status,
        source_domain=source_domain,
        workspace_id=workspace_id,
        app_id=app_id,
        runtime_session_id=runtime_session_id,
        provider_id=provider_id,
        detail=detail,
        payload=redact_payload(payload),
        occurred_at=now or utcnow(),
    )
    return store.save_audit(record)
