"""Runtime restart and recovery intent helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from core.recovery.models import RecoveryIntentRecord
from core.runtime.runtime_session import RuntimeSessionRecord


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def plan_runtime_restart(session: RuntimeSessionRecord, *, reason: str, now: datetime | None = None) -> RecoveryIntentRecord:
    """Create one runtime restart intent for one session."""
    timestamp = now or utcnow()
    return RecoveryIntentRecord(
        intent_id=str(uuid4()),
        workspace_id=session.workspace_id,
        session_id=session.session_id,
        failure_id=None,
        action="restart_runtime",
        reason=reason,
        status="planned",
        created_at=timestamp,
        updated_at=timestamp,
    )


def apply_restart_marker(session: RuntimeSessionRecord, *, now: datetime | None = None) -> RuntimeSessionRecord:
    """Mark one session as failed so recovery can plan a restart out of band."""
    timestamp = now or utcnow()
    return replace(session, status="failed", updated_at=timestamp, ended_at=timestamp)
