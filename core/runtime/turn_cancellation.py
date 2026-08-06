"""Durable runtime turn cancellation intent and transition materialization."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from core.runtime.lifecycle_service_sessions import utcnow
from core.runtime.runtime_turns import RuntimeTurnRecord, RuntimeTurnStatus
from core.runtime.store import RuntimeStore


def request_runtime_turn_cancellation(
    store: RuntimeStore,
    *,
    turn_id: str,
    reason: str,
    now: datetime | None = None,
) -> RuntimeTurnRecord:
    """Publish a durable cancellation fence without waiting for provider acceptance."""
    return store.request_turn_cancellation(
        turn_id=turn_id,
        reason=reason,
        now=now or utcnow(),
    )


def materialize_runtime_turn_transition(
    turn: RuntimeTurnRecord,
    *,
    target_status: RuntimeTurnStatus,
    failure_reason: str | None,
    timestamp: datetime,
) -> RuntimeTurnRecord:
    """Build one lifecycle record while preserving independent control fields."""
    return replace(
        turn,
        status=target_status,
        updated_at=timestamp,
        started_at=turn.started_at or (timestamp if target_status == "active" else None),
        completed_at=(
            timestamp if target_status in {"completed", "failed", "cancelled", "timed-out"} else None
        ),
        failure_reason=failure_reason,
    )
