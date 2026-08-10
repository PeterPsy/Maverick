"""Crash-recoverable runtime turn terminalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import uuid4

from core.runtime.event_bus import RuntimeEventBus
from core.runtime.lifecycle_service_events import record_runtime_turn_event_once
from core.runtime.lifecycle_service_sessions import utcnow
from core.runtime.lifecycle_service_turns import transition_runtime_turn
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_threads import runtime_thread_availability_for_session, update_runtime_thread_availability
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeStore
from core.runtime.turn_cancellation import request_runtime_turn_cancellation


RuntimeTerminalCallback = Callable[
    [RuntimeSessionRecord, RuntimeTurnRecord, RuntimeEventRecord],
    None,
]


@dataclass(frozen=True)
class RuntimeTurnTerminalizationResult:
    """Authoritative turn plus the progress of its durable terminal outbox."""

    turn: RuntimeTurnRecord
    event: RuntimeEventRecord | None
    claimed: bool
    callback_pending: bool


def terminalize_runtime_turn_cancellation(
    store: RuntimeStore,
    *,
    turn_id: str,
    reason: str,
    event_payload: dict[str, object],
    event_bus: RuntimeEventBus | None = None,
    callback: RuntimeTerminalCallback | None = None,
    request_intent: bool = True,
    now: datetime | None = None,
) -> RuntimeTurnTerminalizationResult:
    """Materialize cancellation and drain its persisted phases idempotently."""
    timestamp = now or utcnow()
    if request_intent:
        request_runtime_turn_cancellation(
            store,
            turn_id=turn_id,
            reason=reason,
            now=timestamp,
        )
    updated = transition_runtime_turn(
        store,
        turn_id=turn_id,
        target_status="cancelled",
        failure_reason=reason,
        now=timestamp,
        update_thread=False,
    )
    if updated.status != "cancelled":
        return RuntimeTurnTerminalizationResult(
            turn=updated,
            event=None,
            claimed=False,
            callback_pending=False,
        )
    return drain_runtime_turn_terminalization(
        store,
        turn=updated,
        event_payload=event_payload,
        event_bus=event_bus,
        callback=callback,
        now=timestamp,
    )


def drain_runtime_turn_terminalization(
    store: RuntimeStore,
    *,
    turn: RuntimeTurnRecord,
    event_payload: dict[str, object],
    event_bus: RuntimeEventBus | None = None,
    callback: RuntimeTerminalCallback | None = None,
    now: datetime | None = None,
) -> RuntimeTurnTerminalizationResult:
    """Claim or resume the terminal outbox for an already-terminal turn."""
    if turn.status != "cancelled":
        return RuntimeTurnTerminalizationResult(
            turn=turn,
            event=None,
            claimed=False,
            callback_pending=False,
        )
    timestamp = now or utcnow()
    event_type = "runtime.turn.cancelled"
    existing_event = store.find_turn_event(turn_id=turn.turn_id, event_type=event_type)
    candidate_event_id = existing_event.event_id if existing_event is not None else str(uuid4())
    candidate_payload = dict(existing_event.payload) if existing_event is not None else dict(event_payload)
    candidate_created_at = existing_event.created_at if existing_event is not None else timestamp
    claimed_turn, claimed = store.claim_turn_terminalization(
        turn_id=turn.turn_id,
        event_id=candidate_event_id,
        event_type=event_type,
        payload=candidate_payload,
        now=candidate_created_at,
    )
    event_id = claimed_turn.terminalization_event_id
    if not event_id or claimed_turn.terminalization_event_type != event_type:
        return RuntimeTurnTerminalizationResult(
            turn=claimed_turn,
            event=existing_event,
            claimed=False,
            callback_pending=False,
        )

    # The handoff serializes nominal concurrent drainers. A process crash releases
    # the lock, leaving each persisted phase eligible for a retry.
    with store.session_lifecycle_handoff(
        workspace_id=claimed_turn.workspace_id,
        session_id=claimed_turn.session_id,
    ):
        current = store.get_turn(claimed_turn.turn_id)
        session = store.get_session(current.session_id)
        payload = dict(current.terminalization_event_payload or candidate_payload)
        event = store.find_turn_event(turn_id=current.turn_id, event_type=event_type)
        if current.terminalization_event_persisted_at is None:
            event, _inserted = record_runtime_turn_event_once(
                store,
                event_id=event_id,
                session_id=current.session_id,
                turn_id=current.turn_id,
                event_type=event_type,
                payload=payload,
                now=current.terminalization_claimed_at or candidate_created_at,
                event_bus=event_bus,
            )
            current, _applied = store.mark_turn_terminalization_phase(
                turn_id=current.turn_id,
                event_id=event_id,
                phase="event",
            )
        if event is None:
            event = store.find_turn_event(turn_id=current.turn_id, event_type=event_type)
        if event is None:
            return RuntimeTurnTerminalizationResult(
                turn=current,
                event=None,
                claimed=claimed,
                callback_pending=bool(session.source_app_id),
            )

        if current.terminalization_thread_released_at is None:
            update_runtime_thread_availability(
                store,
                workspace_id=current.workspace_id,
                runtime_session_id=current.session_id,
                availability=runtime_thread_availability_for_session(
                    store,
                    runtime_session_id=current.session_id,
                ),
                now=event.created_at,
            )
            current, _applied = store.mark_turn_terminalization_phase(
                turn_id=current.turn_id,
                event_id=event_id,
                phase="thread",
            )

        callback_pending = False
        if current.terminalization_callback_delivered_at is None:
            if (session.source_app_id or "").strip() and callback is None:
                callback_pending = True
            else:
                try:
                    if callback is not None:
                        callback(session, current, event)
                except Exception:
                    callback_pending = True
                else:
                    current, _applied = store.mark_turn_terminalization_phase(
                        turn_id=current.turn_id,
                        event_id=event_id,
                        phase="callback",
                    )
        return RuntimeTurnTerminalizationResult(
            turn=current,
            event=event,
            claimed=claimed,
            callback_pending=callback_pending,
        )
