"""Structured failure terminalization shared by runtime turn submitters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.runtime.failure_messages import runtime_failure_details
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_process_lifecycle import release_idle_runtime_processes
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import transition_runtime_turn
from core.runtime.turn_submission_service_events import (
    _debug_log_runtime_turn,
    _record_turn_failed,
    _terminalize_worker_observed_cancellation,
)

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


def terminalize_queued_dispatch_failure(
    state: PlatformState,
    *,
    session_id: str,
    turn: RuntimeTurnRecord,
    provider_id: str,
    error: Exception,
) -> tuple[RuntimeTurnRecord, RuntimeEventRecord | None]:
    """Persist a safe queued-callback failure or a concurrent cancellation."""
    failure_reason_code, public_error_message = runtime_failure_details(error)
    failed = transition_runtime_turn(
        state.runtime_store,
        turn_id=turn.turn_id,
        target_status="failed",
        failure_reason=public_error_message,
    )
    if failed.status == "cancelled":
        terminalization = _terminalize_worker_observed_cancellation(
            state,
            turn=failed,
            provider_id=provider_id,
        )
        return terminalization.turn, terminalization.event
    _record_turn_failed(
        state,
        session_id=session_id,
        turn_id=failed.turn_id,
        provider_id=provider_id,
        error=public_error_message,
        failure_reason_code=failure_reason_code,
        diagnostic_reference=f"turn:{failed.turn_id}",
    )
    return failed, None


def terminalize_sync_execution_failure(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    turn: RuntimeTurnRecord,
    provider_id: str,
    error: Exception,
    events: list[RuntimeEventRecord],
    plain_hosted: bool,
) -> RuntimeTurnRecord:
    """Persist one redaction-safe failure while preserving cancellation races."""
    failure_reason_code, public_error_message = runtime_failure_details(error)
    reason_codes = getattr(error, "reason_codes", None)
    _debug_log_runtime_turn(
        state,
        session=session,
        provider_id=provider_id,
        turn_id=turn.turn_id,
        message="Runtime turn debug: sync execution raised",
        payload={
            "phase": "sync_execution_raised",
            "error_type": type(error).__name__,
            "error": failure_reason_code,
        },
    )
    current = state.runtime_store.get_turn(turn.turn_id)
    if current.status == "cancelled":
        terminalization = _terminalize_worker_observed_cancellation(
            state,
            turn=current,
            provider_id=provider_id,
        )
        if terminalization.event is not None:
            events.append(terminalization.event)
        return terminalization.turn
    if current.status in {"completed", "failed", "cancelled", "timed-out"}:
        return current
    failed = transition_runtime_turn(
        state.runtime_store,
        turn_id=turn.turn_id,
        target_status="failed",
        failure_reason=public_error_message,
    )
    if failed.status == "cancelled":
        terminalization = _terminalize_worker_observed_cancellation(
            state,
            turn=failed,
            provider_id=provider_id,
        )
        if terminalization.event is not None:
            events.append(terminalization.event)
        return terminalization.turn
    failed_event = _record_turn_failed(
        state,
        session_id=session.session_id,
        turn_id=failed.turn_id,
        provider_id=provider_id,
        error=public_error_message,
        failure_reason_code=failure_reason_code,
        diagnostic_reference=f"turn:{failed.turn_id}",
        reason_codes=reason_codes if isinstance(reason_codes, list) else None,
    )
    events.append(failed_event)
    dispatch_source_app_runtime_event(
        state,
        session=session,
        turn=failed,
        event_type="runtime.turn.failed",
        failure_reason=public_error_message,
        runtime_event_id=failed_event.event_id,
    )
    if not plain_hosted:
        release_idle_runtime_processes(
            state,
            session_id=session.session_id,
            provider_id=provider_id,
            reason="sync_turn_failed",
            idle_ttl_seconds=0,
        )
    return failed


__all__ = [
    "terminalize_queued_dispatch_failure",
    "terminalize_sync_execution_failure",
]
