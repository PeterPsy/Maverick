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
    for session in state.runtime_store.list_all_sessions():
        if session.status != "running":
            continue
        inspected += 1
        closed_turns += _close_orphan_non_terminal_turn_events(state, session_id=session.session_id)
        interrupted_turns = [
            turn
            for turn in state.runtime_store.list_turns(session.session_id)
            if turn.status in NON_TERMINAL_TURN_STATUSES
        ]
        if not interrupted_turns:
            continue
        recovered += 1
        for turn in interrupted_turns:
            failure_reason = f"Interrupted by {reason}; automatic resume turn queued."
            target_status = "failed" if turn.status == "active" else "cancelled"
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
                    "recovery_action": "automatic_resume_turn",
                },
                event_bus=state.runtime_event_bus,
            )
        submit_runtime_turn_async(
            state,
            session=state.runtime_store.get_session(session.session_id),
            input_text=RESUME_INPUT_TEXT,
            client_message_id=f"backend-restart-resume:{session.session_id}:{uuid4()}",
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


def _close_orphan_non_terminal_turn_events(state: "PlatformState", *, session_id: str) -> int:
    """Close non-terminal turn events whose canonical turn record is missing."""
    terminal_turn_ids = {
        event.turn_id
        for event in state.runtime_store.list_events(session_id)
        if event.turn_id and event.event_type in TERMINAL_TURN_EVENTS
    }
    orphan_status_by_turn_id: dict[str, str] = {}
    for event in state.runtime_store.list_events(session_id):
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
