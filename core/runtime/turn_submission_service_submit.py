"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Callable

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.providers.service import resolve_runtime_backend_for_session
from core.runtime.app_references import input_text_with_app_references
from core.runtime.attachments import input_text_with_attachment_links
from core.runtime.execution import execute_runtime_turn
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import transition_runtime_turn

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.providers.provider_registry import ProviderRegistry


_SESSION_EXECUTION_LOCKS: dict[str, Lock] = {}
_SESSION_EXECUTION_LOCKS_LOCK = Lock()
_ACTIVE_TURN_STATUSES = {"queued", "active"}


def submit_runtime_turn(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    client_message_id: str | None = None,
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    on_queued: Callable[[RuntimeTurnRecord, list[RuntimeEventRecord]], None] | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    """Queue and execute one runtime turn synchronously."""
    provider, _selection, runtime_adapter = resolve_runtime_backend_for_session(state.provider_store, session=session)
    turn, events = _queue_turn_with_event(
        state,
        session=session,
        input_text=input_text,
        provider_id=provider.provider_id,
        client_message_id=client_message_id,
        attachments=attachments,
        app_references=app_references,
    )
    if on_queued is not None:
        try:
            on_queued(turn, events)
        except Exception as error:
            failed = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="failed", failure_reason=str(error))
            _record_turn_failed(state, session_id=session.session_id, turn_id=failed.turn_id, provider_id=provider.provider_id, error=str(error))
            raise
    turn = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")
    events.append(_record_turn_started(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id))
    _debug_log_runtime_turn(
        state,
        session=session,
        provider_id=provider.provider_id,
        turn_id=turn.turn_id,
        message="Runtime turn debug: sync execution started",
        payload={"phase": "sync_execution_started", "turn_status": turn.status},
    )
    with _session_execution_lock(session.session_id):
        try:
            launch_spec = _build_launch_spec_for_execution(state, session=session, provider_id=provider.provider_id)
            provider_input_text = input_text_with_attachment_links(
                input_text=input_text_with_app_references(input_text=input_text, app_references=app_references),
                attachments=attachments,
                workspace_root=session.workspace_root,
            )
            output_recorder = _RuntimeTurnOutputRecorder(state, session_id=session.session_id, turn_id=turn.turn_id)
            result = execute_runtime_turn(
                session=session,
                provider=provider,
                input_text=provider_input_text,
                launch_spec=launch_spec,
                runtime_adapter=runtime_adapter,
                on_provider_thread_id=lambda provider_thread_id: _record_provider_thread_id(state, session=session, provider_id=provider.provider_id, provider_thread_id=provider_thread_id),
                event_sink=output_recorder.record,
            )
        except Exception as error:
            _debug_log_runtime_turn(
                state,
                session=session,
                provider_id=provider.provider_id,
                turn_id=turn.turn_id,
                message="Runtime turn debug: sync execution raised",
                payload={"phase": "sync_execution_raised", "error_type": type(error).__name__, "error": str(error)},
            )
            turn = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="failed", failure_reason=str(error))
            events.append(_record_turn_failed(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id, error=str(error)))
            dispatch_source_app_runtime_event(
                state,
                session=session,
                turn=turn,
                event_type="runtime.turn.failed",
                failure_reason=str(error),
            )
            release_idle_runtime_processes(state, session_id=session.session_id, provider_id=provider.provider_id, reason="sync_turn_failed")
            return turn, events

        _debug_log_runtime_turn(
            state,
            session=session,
            provider_id=provider.provider_id,
            turn_id=turn.turn_id,
            message="Runtime turn debug: sync execution returned",
            payload={"phase": "sync_execution_returned", "exit_code": result.exit_code, "output_text_length": len(result.output_text)},
        )
        final_output_text = output_recorder.final_text(result.output_text)
        app_output_text = output_recorder.complete_text(result.output_text)
        events.append(_record_final_output(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id, output_text=final_output_text, exit_code=result.exit_code))
        turn, terminal_event = _complete_turn_from_exit_code(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id, exit_code=result.exit_code)
        events.append(terminal_event)
        dispatch_source_app_runtime_event(
            state,
            session=session,
            turn=turn,
            event_type=terminal_event.event_type,
            output_text=app_output_text,
            failure_reason=turn.failure_reason or "",
        )
        _debug_log_runtime_turn(
            state,
            session=session,
            provider_id=provider.provider_id,
            turn_id=turn.turn_id,
            message="Runtime turn debug: sync terminal event recorded",
            payload={"phase": "sync_terminal_event_recorded", "turn_status": turn.status, "terminal_event_type": terminal_event.event_type},
        )
        release_idle_runtime_processes(state, session_id=session.session_id, provider_id=provider.provider_id, reason="sync_turn_terminal")
    return turn, events
