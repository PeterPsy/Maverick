"""Backend restart recovery for interrupted runtime work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from core.runtime.errors import RuntimeTurnNotFoundError
from core.runtime.service import record_runtime_event, transition_runtime_turn
from core.runtime.turn_submission import submit_runtime_turn_async

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


RESUME_INPUT_TEXT = "resume"
RESUME_CLIENT_MESSAGE_ID_PREFIX = "backend-restart-resume:"
NON_TERMINAL_TURN_STATUSES = {"queued", "active"}
NON_TERMINAL_TURN_EVENTS = {
    "runtime.turn.queued": "cancelled",
    "runtime.turn.started": "failed",
}
TERMINAL_TURN_EVENTS = {
    "runtime.turn.cancelled",
    "runtime.turn.completed",
    "runtime.turn.failed",
    "runtime.turn.timed-out",
    "runtime.output.final",
}
TERMINAL_STATUS_BY_EVENT = {
    "runtime.turn.cancelled": "cancelled",
    "runtime.turn.completed": "completed",
    "runtime.turn.failed": "failed",
    "runtime.turn.timed-out": "timed-out",
    "runtime.output.final": "completed",
}


@dataclass(frozen=True)
class BackendRestartRecoveryResult:
    """Summary of one backend restart recovery pass."""

    inspected_sessions: int
    recovered_sessions: int
    closed_turns: int
    queued_resume_turns: int


def recover_interrupted_runtime_turns_after_backend_restart(
    state: "PlatformState",
    *,
    reason: str = "backend restart",
) -> BackendRestartRecoveryResult:
    """Resume runtime sessions whose in-memory turn workers died during backend restart."""
    inspected = 0
    recovered = 0
    closed_turns = 0
    queued_resumes = 0
    running_sessions = [
        session
        for session in state.runtime_store.list_all_sessions()
        if session.status == "running"
    ]
    events_by_session_id = _events_by_session_id(state, session_ids={session.session_id for session in running_sessions})
    for session in running_sessions:
        inspected += 1
        session_events = events_by_session_id.get(session.session_id, [])
        closed_turns += _close_orphan_non_terminal_turn_events(
            state,
            session_id=session.session_id,
            events=session_events,
        )
        closed_turns += _close_non_terminal_turns_with_terminal_events(
            state,
            session_id=session.session_id,
            events=session_events,
        )
        interrupted_turns = [
            turn
            for turn in state.runtime_store.list_turns(session.session_id)
            if turn.status in NON_TERMINAL_TURN_STATUSES
        ]
        if not interrupted_turns:
            continue
        recovered += 1
        should_queue_resume = False
        for turn in interrupted_turns:
            is_recovery_resume_turn = _is_backend_restart_resume_turn(turn, session_events)
            failure_reason = f"Interrupted by {reason}; automatic resume turn queued."
            target_status = "failed" if turn.status == "active" else "cancelled"
            if is_recovery_resume_turn:
                failure_reason = f"Interrupted by {reason}; recovery resume turn closed without queuing another resume."
            updated = transition_runtime_turn(
                state.runtime_store,
                turn_id=turn.turn_id,
                target_status=target_status,
                failure_reason=failure_reason,
            )
            closed_turns += 1
            record_runtime_event(
                state.runtime_store,
                event_id=str(uuid4()),
                session_id=session.session_id,
                turn_id=updated.turn_id,
                plane="turn",
                event_type=f"runtime.turn.{target_status}",
                payload={
                    "reason": "backend_restart",
                    "detail": failure_reason,
                    "recovery_action": "close_resume_turn" if is_recovery_resume_turn else "automatic_resume_turn",
                },
                event_bus=state.runtime_event_bus,
            )
            should_queue_resume = should_queue_resume or not is_recovery_resume_turn
        if not should_queue_resume:
            continue
        submit_runtime_turn_async(
            state,
            session=state.runtime_store.get_session(session.session_id),
            input_text=RESUME_INPUT_TEXT,
            client_message_id=f"{RESUME_CLIENT_MESSAGE_ID_PREFIX}{session.session_id}:{uuid4()}",
        )
        queued_resumes += 1
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            plane="runtime",
            event_type="runtime.recovery.resume_queued",
            payload={"reason": "backend_restart", "input_text": RESUME_INPUT_TEXT},
            event_bus=state.runtime_event_bus,
        )
    return BackendRestartRecoveryResult(
        inspected_sessions=inspected,
        recovered_sessions=recovered,
        closed_turns=closed_turns,
        queued_resume_turns=queued_resumes,
    )


def _events_by_session_id(state: "PlatformState", *, session_ids: set[str]) -> dict[str, list]:
    """Group persisted runtime events for the running sessions being recovered."""
    grouped: dict[str, list] = {session_id: [] for session_id in session_ids}
    if not session_ids:
        return grouped
    for event in state.runtime_store.list_all_events():
        if event.session_id in grouped:
            grouped[event.session_id].append(event)
    return grouped


def _close_orphan_non_terminal_turn_events(state: "PlatformState", *, session_id: str, events: list | None = None) -> int:
    """Close non-terminal turn events whose canonical turn record is missing."""
    if events is None:
        events = state.runtime_store.list_events(session_id)
    terminal_turn_ids = {
        event.turn_id
        for event in events
        if event.turn_id and event.event_type in TERMINAL_TURN_EVENTS
    }
    orphan_status_by_turn_id: dict[str, str] = {}
    for event in events:
        if not event.turn_id or event.turn_id in terminal_turn_ids:
            continue
        target_status = NON_TERMINAL_TURN_EVENTS.get(event.event_type)
        if not target_status:
            continue
        try:
            state.runtime_store.get_turn(event.turn_id)
        except RuntimeTurnNotFoundError:
            orphan_status_by_turn_id[event.turn_id] = target_status
    closed = 0
    for turn_id, target_status in orphan_status_by_turn_id.items():
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            plane="turn",
            event_type=f"runtime.turn.{target_status}",
            payload={
                "reason": "backend_restart_orphan_turn_event",
                "detail": "Closed non-terminal runtime event whose turn record was missing.",
            },
            event_bus=state.runtime_event_bus,
        )
        closed += 1
    return closed


def _close_non_terminal_turns_with_terminal_events(state: "PlatformState", *, session_id: str, events: list | None = None) -> int:
    """Reconcile turn records when the event log already proves the turn ended."""
    if events is None:
        events = state.runtime_store.list_events(session_id)
    terminal_event_by_turn_id = _latest_terminal_event_by_turn_id(events)
    if not terminal_event_by_turn_id:
        return 0
    closed = 0
    for turn in state.runtime_store.list_turns(session_id):
        if turn.status not in NON_TERMINAL_TURN_STATUSES:
            continue
        terminal_event = terminal_event_by_turn_id.get(turn.turn_id)
        if terminal_event is None:
            continue
        target_status = TERMINAL_STATUS_BY_EVENT.get(terminal_event.event_type)
        if target_status is None:
            continue
        updated = _transition_turn_to_terminal_status(
            state,
            turn_id=turn.turn_id,
            current_status=turn.status,
            target_status=target_status,
            failure_reason=_failure_reason_from_terminal_event(terminal_event),
        )
        closed += 1
        canonical_event_type = f"runtime.turn.{updated.status}"
        if terminal_event.event_type != canonical_event_type:
            record_runtime_event(
                state.runtime_store,
                event_id=str(uuid4()),
                session_id=session_id,
                turn_id=updated.turn_id,
                plane="turn",
                event_type=canonical_event_type,
                payload={
                    "reason": "backend_restart_terminal_event_reconciliation",
                    "source_event_id": terminal_event.event_id,
                },
                event_bus=state.runtime_event_bus,
            )
    return closed


def _latest_terminal_event_by_turn_id(events: list) -> dict[str, object]:
    terminal_event_by_turn_id: dict[str, object] = {}
    ordered_events = sorted(events, key=lambda event: (event.created_at, event.event_id))
    for event in ordered_events:
        if event.turn_id and event.event_type in TERMINAL_STATUS_BY_EVENT:
            terminal_event_by_turn_id[event.turn_id] = event
    return terminal_event_by_turn_id


def _transition_turn_to_terminal_status(
    state: "PlatformState",
    *,
    turn_id: str,
    current_status: str,
    target_status: str,
    failure_reason: str | None,
):
    if current_status == "queued" and target_status in {"completed", "failed"}:
        transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="active")
    return transition_runtime_turn(
        state.runtime_store,
        turn_id=turn_id,
        target_status=target_status,
        failure_reason=failure_reason,
    )


def _failure_reason_from_terminal_event(event) -> str | None:
    if event.event_type != "runtime.turn.failed":
        return None
    error = event.payload.get("error")
    detail = event.payload.get("detail")
    return str(error or detail or "Runtime turn failed.")


def _is_backend_restart_resume_turn(turn, events: list) -> bool:
    if turn.input_text != RESUME_INPUT_TEXT:
        return False
    for event in events:
        if event.turn_id != turn.turn_id or event.event_type != "runtime.turn.queued":
            continue
        client_message_id = event.payload.get("client_message_id")
        if isinstance(client_message_id, str) and client_message_id.startswith(RESUME_CLIENT_MESSAGE_ID_PREFIX):
            return True
    return False
