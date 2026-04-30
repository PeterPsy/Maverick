"""Backend restart recovery for interrupted runtime work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event, dispatch_workspace_app_background_hooks
from core.providers.errors import ProviderError
from core.runtime.errors import RuntimeTurnNotFoundError
from core.runtime.service import record_runtime_event, transition_runtime_turn
from core.runtime.store import MAX_RUNTIME_EVENTS_PER_SESSION
from core.runtime.turn_submission import _complete_output_text, submit_runtime_turn_async

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


BACKEND_RESTART_CONTINUATION_INPUT_TEXT = (
    "The backend restarted successfully. Continue from where you left off using the prior conversation and current workspace state."
)
RESUME_CLIENT_MESSAGE_ID_PREFIX = "backend-restart-resume:"
MAX_BACKEND_RESTART_RESUME_ATTEMPTS_PER_SESSION = 3
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
        resume_attempts = _backend_restart_resume_attempt_count(session_events)
        for turn in interrupted_turns:
            is_recovery_resume_turn = _is_backend_restart_resume_turn(turn, session_events)
            failure_reason = f"Interrupted by {reason}; automatic resume turn queued."
            recovery_action = "automatic_resume_turn"
            target_status = "failed" if turn.status == "active" else "cancelled"
            if is_recovery_resume_turn:
                if resume_attempts >= MAX_BACKEND_RESTART_RESUME_ATTEMPTS_PER_SESSION:
                    failure_reason = f"Interrupted by {reason}; recovery resume retry limit reached."
                    recovery_action = "close_resume_turn"
                else:
                    failure_reason = f"Interrupted by {reason}; recovery resume retry queued."
                    recovery_action = "retry_resume_turn"
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
                    "recovery_action": recovery_action,
                    "resume_attempts": resume_attempts if is_recovery_resume_turn else None,
                    "max_resume_attempts": MAX_BACKEND_RESTART_RESUME_ATTEMPTS_PER_SESSION if is_recovery_resume_turn else None,
                },
                event_bus=state.runtime_event_bus,
            )
            dispatch_source_app_runtime_event(
                state,
                session=state.runtime_store.get_session(session.session_id),
                turn=updated,
                event_type=f"runtime.turn.{target_status}",
                failure_reason=updated.failure_reason or failure_reason,
            )
            should_queue_resume = should_queue_resume or recovery_action in {"automatic_resume_turn", "retry_resume_turn"}
        if not should_queue_resume:
            continue
        try:
            submit_runtime_turn_async(
                state,
                session=state.runtime_store.get_session(session.session_id),
                input_text=BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
                client_message_id=f"{RESUME_CLIENT_MESSAGE_ID_PREFIX}{session.session_id}:{uuid4()}",
                on_queued=lambda queued_turn, _events, session_id=session.session_id: dispatch_source_app_runtime_event(
                    state,
                    session=state.runtime_store.get_session(session_id),
                    turn=queued_turn,
                    event_type="runtime.turn.queued",
                ),
            )
        except ProviderError as error:
            record_runtime_event(
                state.runtime_store,
                event_id=str(uuid4()),
                session_id=session.session_id,
                plane="runtime",
                event_type="runtime.recovery.resume_blocked",
                payload={
                    "reason": "backend_restart",
                    "blocked_reason": "no_provider_configured" if str(error) == "no_provider_configured" else "provider_unavailable",
                    "detail": str(error),
                },
                event_bus=state.runtime_event_bus,
            )
            continue
        queued_resumes += 1
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            plane="runtime",
            event_type="runtime.recovery.resume_queued",
            payload={"reason": "backend_restart", "input_text": BACKEND_RESTART_CONTINUATION_INPUT_TEXT},
            event_bus=state.runtime_event_bus,
        )
    for workspace in state.workspace_store.list_workspaces():
        dispatch_workspace_app_background_hooks(
            state,
            workspace_id=workspace.workspace_id,
            hook_name="backend_recovery",
            action="backend.recovery",
            body={"reason": reason},
            start_path=state.repository_root,
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
    for session_id in session_ids:
        grouped[session_id] = state.runtime_store.list_recent_events(session_id, limit=MAX_RUNTIME_EVENTS_PER_SESSION)
    return grouped


def _close_orphan_non_terminal_turn_events(state: "PlatformState", *, session_id: str, events: list | None = None) -> int:
    """Close non-terminal turn events whose canonical turn record is missing."""
    if events is None:
        events = state.runtime_store.list_recent_events(session_id, limit=MAX_RUNTIME_EVENTS_PER_SESSION)
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
        events = state.runtime_store.list_recent_events(session_id, limit=MAX_RUNTIME_EVENTS_PER_SESSION)
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
        dispatch_source_app_runtime_event(
            state,
            session=state.runtime_store.get_session(session_id),
            turn=updated,
            event_type=canonical_event_type,
            output_text=_output_text_for_turn(events, updated.turn_id),
            failure_reason=updated.failure_reason or "",
        )
    return closed


def _latest_terminal_event_by_turn_id(events: list) -> dict[str, object]:
    terminal_event_by_turn_id: dict[str, object] = {}
    ordered_events = sorted(events, key=lambda event: (event.created_at, event.event_id))
    for event in ordered_events:
        if event.turn_id and event.event_type in TERMINAL_STATUS_BY_EVENT:
            terminal_event_by_turn_id[event.turn_id] = event
    return terminal_event_by_turn_id


def _output_text_for_turn(events: list, turn_id: str) -> str:
    streamed_text = "".join(
        str(event.payload.get("text") or "")
        for event in events
        if event.turn_id == turn_id
        and event.event_type == "runtime.output.delta"
        and isinstance(event.payload, dict)
    )
    output_events = [
        event
        for event in events
        if event.turn_id == turn_id and event.event_type == "runtime.output.final" and isinstance(event.payload, dict)
    ]
    if not output_events:
        return streamed_text
    latest = sorted(output_events, key=lambda event: (event.created_at, event.event_id))[-1]
    return _complete_output_text(str(latest.payload.get("text") or ""), streamed_text)


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
    if turn.input_text != BACKEND_RESTART_CONTINUATION_INPUT_TEXT:
        return False
    for event in events:
        if event.turn_id != turn.turn_id or event.event_type != "runtime.turn.queued":
            continue
        client_message_id = event.payload.get("client_message_id")
        if isinstance(client_message_id, str) and client_message_id.startswith(RESUME_CLIENT_MESSAGE_ID_PREFIX):
            return True
    return False


def _backend_restart_resume_attempt_count(events: list) -> int:
    count = 0
    for event in events:
        if event.event_type == "runtime.recovery.resume_queued":
            count += 1
            continue
        if event.event_type != "runtime.turn.queued":
            continue
        client_message_id = event.payload.get("client_message_id")
        if isinstance(client_message_id, str) and client_message_id.startswith(RESUME_CLIENT_MESSAGE_ID_PREFIX):
            count += 1
    return count
