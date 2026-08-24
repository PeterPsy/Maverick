"""Backend restart recovery for interrupted runtime work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event, dispatch_workspace_app_background_hooks
from core.inter_agent.service import InterAgentService
from core.providers.errors import ProviderError
from core.runtime.errors import RuntimeTurnNotFoundError
from core.runtime.plain_hosted_cancellation import reconcile_stale_plain_hosted_request_owners
from core.runtime.service import record_runtime_event, transition_runtime_turn
from core.runtime.store import MAX_RUNTIME_EVENTS_PER_SESSION
from core.runtime.thread_catalog_events import set_thread_availability
from core.runtime.turn_submission import _complete_output_text, submit_runtime_turn_async
from core.runtime.turn_terminalization import (
    drain_runtime_turn_terminalization,
    migrate_legacy_cancelled_turn_terminalization,
)
from core.skills.service import SkillInvocationError

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.runtime.runtime_turns import RuntimeTurnRecord


logger = logging.getLogger(__name__)


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
    reconcile_stale_plain_hosted_request_owners(state.runtime_store)
    _recover_pending_cancelled_turn_terminalizations(state)
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
        resume_source_turn: RuntimeTurnRecord | None = None
        resume_source_rank: tuple[int, datetime, str] | None = None
        resume_attempts = _backend_restart_resume_attempt_count(session_events)
        has_app_stream = state.runtime_store.has_nonterminal_app_stream_for_session(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
        )
        for turn in interrupted_turns:
            is_recovery_resume_turn = _is_backend_restart_resume_turn(turn, session_events)
            is_inter_agent_root_turn = _is_inter_agent_root_turn(turn, session_events)
            failure_reason = f"Interrupted by {reason}; automatic resume turn queued."
            recovery_action = "automatic_resume_turn"
            target_status = "failed" if turn.status == "active" else "cancelled"
            if has_app_stream:
                failure_reason = f"Interrupted by {reason}; source app retry remains idempotent."
                recovery_action = "close_app_stream_turn"
            elif is_inter_agent_root_turn:
                failure_reason = f"Interrupted by {reason}; inter-agent run recovery will close the run."
                recovery_action = "close_inter_agent_root_turn"
            elif session.session_kind == "inter_agent_participant":
                failure_reason = f"Interrupted by {reason}; the persisted inter-agent scheduler will retry the task."
                recovery_action = "close_inter_agent_participant_turn"
            elif is_recovery_resume_turn:
                if resume_attempts >= MAX_BACKEND_RESTART_RESUME_ATTEMPTS_PER_SESSION:
                    failure_reason = f"Interrupted by {reason}; recovery resume retry limit reached."
                    recovery_action = "close_resume_turn"
                else:
                    failure_reason = f"Interrupted by {reason}; recovery resume retry queued."
                    recovery_action = "retry_resume_turn"
            if recovery_action in {"automatic_resume_turn", "retry_resume_turn"}:
                target_status = "failed"
            updated = transition_runtime_turn(
                state.runtime_store,
                turn_id=turn.turn_id,
                target_status=target_status,
                failure_reason=failure_reason,
            )
            recovery_action = _recovery_action_for_updated_status(
                updated_status=updated.status,
                planned_action=recovery_action,
            )
            terminal_event_type = f"runtime.turn.{updated.status}"
            terminal_detail = updated.failure_reason or failure_reason
            closed_turns += 1
            terminal_payload = {
                "reason": "backend_restart",
                "detail": terminal_detail,
                "recovery_action": recovery_action,
                "resume_attempts": resume_attempts if is_recovery_resume_turn else None,
                "max_resume_attempts": MAX_BACKEND_RESTART_RESUME_ATTEMPTS_PER_SESSION if is_recovery_resume_turn else None,
            }
            if updated.status == "cancelled":
                drain_runtime_turn_terminalization(
                    state.runtime_store,
                    turn=updated,
                    event_payload=terminal_payload,
                    event_bus=state.runtime_event_bus,
                    callback=_source_app_terminal_callback(
                        state,
                        failure_reason=terminal_detail,
                    ),
                )
            else:
                event = record_runtime_event(
                    state.runtime_store,
                    event_id=str(uuid4()),
                    session_id=session.session_id,
                    turn_id=updated.turn_id,
                    plane="turn",
                    event_type=terminal_event_type,
                    payload=terminal_payload,
                    event_bus=state.runtime_event_bus,
                )
                set_thread_availability(
                    state,
                    workspace_id=updated.workspace_id,
                    runtime_session_id=session.session_id,
                    availability="free",
                    now=event.created_at,
                )
                dispatch_source_app_runtime_event(
                    state,
                    session=state.runtime_store.get_session(session.session_id),
                    turn=updated,
                    event_type=terminal_event_type,
                    failure_reason=terminal_detail,
                    runtime_event_id=event.event_id,
                )
            should_queue_resume = should_queue_resume or (
                updated.status == "failed"
                and recovery_action in {"automatic_resume_turn", "retry_resume_turn"}
            )
            if updated.status == "failed" and recovery_action in {"automatic_resume_turn", "retry_resume_turn"}:
                candidate_rank = (1 if turn.status == "active" else 0, turn.updated_at, turn.turn_id)
                if resume_source_rank is None or candidate_rank > resume_source_rank:
                    resume_source_turn = updated
                    resume_source_rank = candidate_rank
        if not should_queue_resume:
            continue
        try:
            submit_runtime_turn_async(
                state,
                session=state.runtime_store.get_session(session.session_id),
                input_text=BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
                client_message_id=f"{RESUME_CLIENT_MESSAGE_ID_PREFIX}{session.session_id}:{uuid4()}",
                invoked_skill_ids=list(resume_source_turn.invoked_skill_ids) if resume_source_turn is not None else [],
                on_queued=lambda queued_turn, _events, session_id=session.session_id: dispatch_source_app_runtime_event(
                    state,
                    session=state.runtime_store.get_session(session_id),
                    turn=queued_turn,
                    event_type="runtime.turn.queued",
                ),
            )
        except (ProviderError, SkillInvocationError) as error:
            if isinstance(error, SkillInvocationError):
                blocked_reason = error.reason_code
            else:
                blocked_reason = (
                    "no_provider_configured"
                    if str(error) == "no_provider_configured"
                    else "provider_unavailable"
                )
            record_runtime_event(
                state.runtime_store,
                event_id=str(uuid4()),
                session_id=session.session_id,
                plane="runtime",
                event_type="runtime.recovery.resume_blocked",
                payload={
                    "reason": "backend_restart",
                    "blocked_reason": blocked_reason,
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
            payload={
                "reason": "backend_restart",
                "input_text": BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
                "invoked_skill_ids": list(resume_source_turn.invoked_skill_ids) if resume_source_turn is not None else [],
            },
            event_bus=state.runtime_event_bus,
        )
    for workspace in state.workspace_store.list_workspaces():
        InterAgentService(state.inter_agent_store).recover_non_terminal_runs(
            state.runtime_store,
            workspace_id=workspace.workspace_id,
        )
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


def _recover_pending_cancelled_turn_terminalizations(state: "PlatformState") -> int:
    """Drain cancellation outboxes left between phases by a terminated process."""
    recovered = 0
    for session in state.runtime_store.list_all_sessions():
        for turn in state.runtime_store.list_turns(session.session_id):
            if turn.status != "cancelled":
                continue
            try:
                recovered += int(_recover_one_cancelled_turn_terminalization(state, turn=turn))
            except Exception:
                logger.exception(
                    "Backend restart could not recover cancelled turn terminalization: session_id=%s turn_id=%s",
                    session.session_id,
                    turn.turn_id,
                )
    return recovered


def _recover_one_cancelled_turn_terminalization(
    state: "PlatformState",
    *,
    turn: "RuntimeTurnRecord",
) -> bool:
    """Recover one cancellation without allowing its corruption to block peer turns."""
    if turn.terminalization_event_id is None:
        legacy_event = state.runtime_store.find_turn_event(
            turn_id=turn.turn_id,
            event_type="runtime.turn.cancelled",
        )
        if legacy_event is not None:
            migrated = migrate_legacy_cancelled_turn_terminalization(
                state.runtime_store,
                turn=turn,
                event=legacy_event,
            )
            return migrated.claimed
        if turn.cancellation_requested_at is None:
            return False
    if (
        turn.terminalization_event_persisted_at is not None
        and turn.terminalization_thread_released_at is not None
        and turn.terminalization_callback_delivered_at is not None
    ):
        return False
    reason = turn.cancellation_reason or turn.failure_reason or "Runtime turn cancelled."
    result = drain_runtime_turn_terminalization(
        state.runtime_store,
        turn=turn,
        event_payload={"reason": reason, "recovery_action": "drain_terminalization_outbox"},
        event_bus=state.runtime_event_bus,
        callback=_source_app_terminal_callback(state, failure_reason=reason),
    )
    return bool(
        result.event is not None
        and not result.callback_pending
        and result.turn.terminalization_event_persisted_at is not None
        and result.turn.terminalization_thread_released_at is not None
        and result.turn.terminalization_callback_delivered_at is not None
    )


def _source_app_terminal_callback(state: "PlatformState", *, failure_reason: str):
    def callback(session, turn, event) -> None:
        dispatch_source_app_runtime_event(
            state,
            session=session,
            turn=turn,
            event_type=event.event_type,
            failure_reason=failure_reason,
            runtime_event_id=event.event_id,
            raise_on_failure=True,
            start_path=state.repository_root,
        )

    return callback


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
        set_thread_availability(
            state,
            workspace_id=updated.workspace_id,
            runtime_session_id=session_id,
            availability="free",
            now=terminal_event.created_at,
        )
        closed += 1
        canonical_event_type = f"runtime.turn.{updated.status}"
        canonical_event = terminal_event
        if terminal_event.event_type != canonical_event_type:
            canonical_event = record_runtime_event(
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
            runtime_event_id=canonical_event.event_id,
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
    complete_text = str(latest.payload.get("complete_text") or "")
    if complete_text:
        return complete_text
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


def _is_inter_agent_root_turn(turn, events: list) -> bool:
    for event in events:
        if event.turn_id != turn.turn_id or not isinstance(event.payload, dict):
            continue
        if str(event.payload.get("inter_agent_run_id") or "").strip():
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


def _recovery_action_for_updated_status(*, updated_status: str, planned_action: str) -> str:
    if updated_status == "failed":
        return planned_action
    return f"preserve_{updated_status.replace('-', '_')}_turn"
