"""Backend restart recovery for interrupted runtime work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from core.runtime.service import record_runtime_event, transition_runtime_turn
from core.runtime.turn_submission import submit_runtime_turn_async

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


RESUME_INPUT_TEXT = "resume"
NON_TERMINAL_TURN_STATUSES = {"queued", "active"}


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
