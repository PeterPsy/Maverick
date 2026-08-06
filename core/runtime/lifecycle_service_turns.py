"""Runtime session, turn, event, and process lifecycle helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import time
from typing import TYPE_CHECKING

from core.runtime.errors import RuntimeTransitionError
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.lifecycle_service_sessions import _transition_allowed, utcnow
from core.runtime.output_compaction import ToolOutputCompactionContext, compact_tool_call_event
from core.runtime.runtime_events import RuntimeEventPlane, RuntimeEventRecord
from core.runtime.runtime_process import RuntimeProcessRecord, RuntimeProcessStatus
from core.runtime.runtime_threads import mark_runtime_thread_response_completed, update_runtime_thread_availability
from core.runtime.runtime_turns import RuntimeTurnRecord, RuntimeTurnStatus
from core.runtime.store import RuntimeStore
from core.runtime.turn_cancellation import (
    materialize_runtime_turn_transition,
    request_runtime_turn_cancellation,
)

if TYPE_CHECKING:
    from core.runtime.event_bus import RuntimeEventBus


def record_runtime_event(
    store: RuntimeStore,
    *,
    event_id: str,
    session_id: str,
    plane: RuntimeEventPlane,
    event_type: str,
    payload: dict,
    turn_id: str | None = None,
    process_id: str | None = None,
    now: datetime | None = None,
    event_bus: "RuntimeEventBus | None" = None,
) -> RuntimeEventRecord:
    """Persist one structured runtime-domain event."""
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    payload = _compacted_runtime_event_payload(
        event_type=event_type,
        plane=plane,
        payload=payload,
        session_id=session_id,
        turn_id=turn_id,
    )
    event = RuntimeEventRecord(
        event_id=event_id,
        workspace_id=session.workspace_id,
        session_id=session_id,
        plane=plane,
        event_type=event_type,
        turn_id=turn_id,
        process_id=process_id,
        payload=payload,
        created_at=timestamp,
    )
    saved = store.save_event(event)
    if event_bus is not None:
        event_bus.publish(saved)
    return saved


def _compacted_runtime_event_payload(
    *,
    event_type: str,
    plane: RuntimeEventPlane,
    payload: dict,
    session_id: str,
    turn_id: str | None,
) -> dict:
    if not event_type.startswith("runtime.tool_call."):
        return payload
    event = compact_tool_call_event(
        RuntimeExecutionEvent(event_type=event_type, payload=payload, plane=plane),
        context=ToolOutputCompactionContext(session_id=session_id, turn_id=turn_id),
    )
    return event.payload


def transition_runtime_turn(
    store: RuntimeStore,
    *,
    turn_id: str,
    target_status: RuntimeTurnStatus,
    failure_reason: str | None = None,
    now: datetime | None = None,
    timing_payload: dict[str, float] | None = None,
    update_thread: bool = True,
) -> RuntimeTurnRecord:
    """Compare and transition one persisted turn under its session handoff."""
    timestamp = now or utcnow()
    location = store.get_turn(turn_id)
    if target_status == "cancelled" and location.status in {"queued", "active"}:
        location = request_runtime_turn_cancellation(
            store,
            turn_id=turn_id,
            reason=failure_reason or "Runtime turn cancelled.",
            now=timestamp,
        )
    with store.session_lifecycle_handoff(
        workspace_id=location.workspace_id,
        session_id=location.session_id,
    ):
        turn = store.get_turn(turn_id)
        allowed: dict[RuntimeTurnStatus, set[RuntimeTurnStatus]] = {
            "queued": {"active", "failed", "cancelled", "timed-out"},
            "active": {"completed", "failed", "cancelled", "timed-out"},
            "completed": set(),
            "failed": set(),
            "cancelled": set(),
            "timed-out": set(),
        }
        effective_target = target_status
        effective_failure_reason = failure_reason
        if turn.cancellation_requested_at is not None:
            effective_target = "cancelled"
            effective_failure_reason = turn.cancellation_reason or failure_reason or "Runtime turn cancelled."
        if turn.status == effective_target:
            return turn
        if turn.status in {"completed", "failed", "cancelled", "timed-out"}:
            if effective_target != "cancelled" or turn.cancellation_requested_at is None:
                if target_status == "cancelled":
                    return turn
                _transition_allowed(turn.status, effective_target, allowed=allowed, kind="runtime turn")
        else:
            _transition_allowed(turn.status, effective_target, allowed=allowed, kind="runtime turn")
        session = store.get_session(turn.session_id)
        if effective_target == "active" and session.status not in {"created", "running"}:
            raise RuntimeTransitionError(
                f"Cannot activate runtime turn while session `{session.session_id}` is {session.status}."
            )
        updated = materialize_runtime_turn_transition(
            turn,
            target_status=effective_target,
            failure_reason=effective_failure_reason,
            timestamp=timestamp,
        )
        save_turn_started_at = time.perf_counter()
        if effective_target == "cancelled":
            saved = store.save_turn(updated)
        else:
            saved, applied = store.save_turn_if_cancellation_absent(
                updated,
                expected_status=turn.status,
            )
            if not applied:
                if saved.cancellation_requested_at is None:
                    raise RuntimeTransitionError(
                        f"Runtime turn `{turn.turn_id}` changed concurrently during transition."
                    )
                saved = store.save_turn(
                    materialize_runtime_turn_transition(
                        saved,
                        target_status="cancelled",
                        failure_reason=saved.cancellation_reason or "Runtime turn cancelled.",
                        timestamp=timestamp,
                    )
                )
        _record_transition_timing(timing_payload, "save_turn_ms", save_turn_started_at)
        state = store.get_state(turn.session_id)
        save_state_started_at = time.perf_counter()
        store.save_state(
            replace(
                state,
                current_turn_id=turn.turn_id if saved.status == "active" else None,
                turn_status=saved.status if saved.status == "active" else None,
                last_progress_at=timestamp,
                last_error_detail=(
                    saved.failure_reason
                    if saved.status in {"failed", "timed-out"}
                    else state.last_error_detail
                ),
                updated_at=timestamp,
            )
        )
        _record_transition_timing(timing_payload, "save_state_ms", save_state_started_at)
        save_session_started_at = time.perf_counter()
        store.save_session(replace(session, last_progress_at=timestamp, updated_at=timestamp))
        _record_transition_timing(timing_payload, "save_session_ms", save_session_started_at)
        if update_thread:
            thread_update_started_at = time.perf_counter()
            _update_thread_for_turn_transition(store, saved)
            _record_transition_timing(timing_payload, "thread_update_ms", thread_update_started_at)
        elif timing_payload is not None:
            timing_payload["thread_update_ms"] = 0.0
        return saved


def _record_transition_timing(timing_payload: dict[str, float] | None, key: str, started_at: float) -> None:
    if timing_payload is not None:
        timing_payload[key] = round((time.perf_counter() - started_at) * 1000, 3)


def _update_thread_for_turn_transition(store: RuntimeStore, turn: RuntimeTurnRecord) -> None:
    if turn.status == "completed":
        mark_runtime_thread_response_completed(
            store,
            workspace_id=turn.workspace_id,
            runtime_session_id=turn.session_id,
            turn_id=turn.turn_id,
            availability="free",
            now=turn.completed_at or turn.updated_at,
        )
        return
    availability = "active" if turn.status == "active" else "queued" if turn.status == "queued" else "free"
    update_runtime_thread_availability(
        store,
        workspace_id=turn.workspace_id,
        runtime_session_id=turn.session_id,
        availability=availability,
        now=turn.updated_at,
    )



def create_runtime_process(
    store: RuntimeStore,
    *,
    process_id: str,
    session_id: str,
    command: list[str],
    cwd: str | None = None,
    now: datetime | None = None,
) -> RuntimeProcessRecord:
    """Create one local runtime process handle record."""
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    return store.save_process(
        RuntimeProcessRecord(
            process_id=process_id,
            session_id=session_id,
            workspace_id=session.workspace_id,
            status="created",
            command=command,
            cwd=cwd or session.workdir,
            stdin_open=False,
            stdout_open=False,
            exit_code=None,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=None,
            ended_at=None,
            failure_reason=None,
        )
    )



def transition_runtime_process(
    store: RuntimeStore,
    *,
    process_id: str,
    target_status: RuntimeProcessStatus,
    exit_code: int | None = None,
    failure_reason: str | None = None,
    stdin_open: bool | None = None,
    stdout_open: bool | None = None,
    now: datetime | None = None,
) -> RuntimeProcessRecord:
    """Transition one runtime process handle between canonical states."""
    timestamp = now or utcnow()
    process = store.get_process(process_id)
    allowed: dict[RuntimeProcessStatus, set[RuntimeProcessStatus]] = {
        "created": {"running", "failed", "terminated"},
        "running": {"exited", "failed", "terminated", "timed-out"},
        "exited": set(),
        "failed": set(),
        "terminated": set(),
        "timed-out": set(),
    }
    _transition_allowed(process.status, target_status, allowed=allowed, kind="runtime process")
    return store.save_process(
        replace(
            process,
            status=target_status,
            stdin_open=stdin_open if stdin_open is not None else process.stdin_open,
            stdout_open=stdout_open if stdout_open is not None else process.stdout_open,
            exit_code=exit_code,
            updated_at=timestamp,
            started_at=process.started_at or (timestamp if target_status == "running" else None),
            ended_at=timestamp if target_status in {"exited", "failed", "terminated", "timed-out"} else None,
            failure_reason=failure_reason,
        )
    )
