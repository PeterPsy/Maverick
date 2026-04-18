"""Failed-start diagnosis and recovery planning."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.recovery.models import FailureCategory, RecoveryIntentRecord, RuntimeFailureRecord


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _recoverability_for_category(category: FailureCategory) -> str:
    if category == "process_crash":
        return "restartable"
    if category in {"missing_secret", "invalid_provider_setup", "health_check_failed", "contract_failure"}:
        return "repair_first"
    return "manual"


def _recovery_action_for_category(category: FailureCategory) -> str:
    if category == "process_crash":
        return "restart_runtime"
    if category in {"missing_secret", "invalid_provider_setup", "health_check_failed", "contract_failure"}:
        return "repair_then_restart"
    return "manual_intervention"


def classify_failed_start(
    *,
    category: FailureCategory,
    detail: str,
    workspace_id: str | None = None,
    session_id: str | None = None,
    now: datetime | None = None,
) -> RuntimeFailureRecord:
    """Create one failed-start record with canonical recoverability."""
    return RuntimeFailureRecord(
        failure_id=str(uuid4()),
        workspace_id=workspace_id,
        session_id=session_id,
        category=category,
        recoverability=_recoverability_for_category(category),
        detail=detail,
        created_at=now or utcnow(),
    )


def plan_failed_start_recovery(
    failure: RuntimeFailureRecord,
    *,
    now: datetime | None = None,
) -> RecoveryIntentRecord:
    """Plan one recovery intent from one failed-start failure."""
    timestamp = now or utcnow()
    return RecoveryIntentRecord(
        intent_id=str(uuid4()),
        workspace_id=failure.workspace_id,
        session_id=failure.session_id,
        failure_id=failure.failure_id,
        action=_recovery_action_for_category(failure.category),
        reason=failure.detail,
        status="planned",
        created_at=timestamp,
        updated_at=timestamp,
    )
