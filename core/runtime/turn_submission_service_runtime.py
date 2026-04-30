"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from contextlib import suppress
from threading import Lock, Thread
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.providers.service import resolve_runtime_backend_for_session
from core.runtime.attachments import input_text_with_attachment_links
from core.runtime.execution import execute_runtime_turn
from core.runtime.process_control import terminate_runtime_processes
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import record_runtime_event, transition_runtime_turn

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.providers.provider_registry import ProviderRegistry


_SESSION_EXECUTION_LOCKS: dict[str, Lock] = {}
_SESSION_EXECUTION_LOCKS_LOCK = Lock()
_ACTIVE_TURN_STATUSES = {"queued", "active"}


def submit_runtime_turn_async(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    client_message_id: str | None = None,
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    on_queued: Callable[[RuntimeTurnRecord, list[RuntimeEventRecord]], None] | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    """Queue one runtime turn and execute it in a background worker."""
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

    def worker() -> None:
        with _session_execution_lock(session.session_id):
            _debug_log_runtime_turn(
                state,
                session=session,
                provider_id=provider.provider_id,
                turn_id=turn.turn_id,
                message="Runtime turn debug: async worker entered",
                payload={"phase": "async_worker_entered"},
            )
            try:
                current = state.runtime_store.get_turn(turn.turn_id)
                if current.status == "cancelled":
                    _debug_log_runtime_turn(
                        state,
                        session=session,
                        provider_id=provider.provider_id,
                        turn_id=turn.turn_id,
                        message="Runtime turn debug: async worker saw pre-cancelled turn",
                        payload={"phase": "async_worker_pre_cancelled"},
                    )
                    return
                active = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")
                _record_turn_started(state, session_id=session.session_id, turn_id=active.turn_id, provider_id=provider.provider_id)
                current_session = state.runtime_store.get_session(session.session_id)
                _debug_log_runtime_turn(
                    state,
                    session=current_session,
                    provider_id=provider.provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async execution started",
                    payload={"phase": "async_execution_started", "turn_status": active.status},
                )
                launch_spec = _build_launch_spec_for_execution(state, session=current_session, provider_id=provider.provider_id)
                provider_input_text = input_text_with_attachment_links(
                    input_text=input_text_with_app_references(input_text=input_text, app_references=app_references),
                    attachments=attachments,
                    workspace_root=current_session.workspace_root,
                )
                output_recorder = _RuntimeTurnOutputRecorder(state, session_id=session.session_id, turn_id=turn.turn_id)
                result = execute_runtime_turn(
                    session=current_session,
                    provider=provider,
                    input_text=provider_input_text,
                    launch_spec=launch_spec,
                    runtime_adapter=runtime_adapter,
                    on_provider_thread_id=lambda provider_thread_id: _record_provider_thread_id(
                        state,
                        session=current_session,
                        provider_id=provider.provider_id,
                        provider_thread_id=provider_thread_id,
                    ),
                    event_sink=output_recorder.record,
                )
                _debug_log_runtime_turn(
                    state,
                    session=current_session,
                    provider_id=provider.provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async execution returned",
                    payload={"phase": "async_execution_returned", "exit_code": result.exit_code, "output_text_length": len(result.output_text)},
                )
                current = state.runtime_store.get_turn(turn.turn_id)
                if current.status == "cancelled":
                    _debug_log_runtime_turn(
                        state,
                        session=current_session,
                        provider_id=provider.provider_id,
                        turn_id=turn.turn_id,
                        message="Runtime turn debug: async worker saw post-execution cancellation",
                        payload={"phase": "async_worker_post_execution_cancelled"},
                    )
                    return
                final_output_text = output_recorder.final_text(result.output_text)
                app_output_text = output_recorder.complete_text(result.output_text)
                _record_final_output(
                    state,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    provider_id=provider.provider_id,
                    output_text=final_output_text,
                    exit_code=result.exit_code,
                )
                completed_turn, terminal_event = _complete_turn_from_exit_code(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider.provider_id, exit_code=result.exit_code)
                dispatch_source_app_runtime_event(
                    state,
                    session=current_session,
                    turn=completed_turn,
                    event_type=terminal_event.event_type,
                    output_text=app_output_text,
                    failure_reason=completed_turn.failure_reason or "",
                )
                _debug_log_runtime_turn(
                    state,
                    session=current_session,
                    provider_id=provider.provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async terminal event recorded",
                    payload={"phase": "async_terminal_event_recorded", "turn_status": completed_turn.status, "terminal_event_type": terminal_event.event_type},
                )
            except Exception as error:
                _debug_log_runtime_turn(
                    state,
                    session=session,
                    provider_id=provider.provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async worker raised",
                    payload={"phase": "async_worker_raised", "error_type": type(error).__name__, "error": str(error)},
                )
                current = state.runtime_store.get_turn(turn.turn_id)
                if current.status not in {"completed", "failed", "cancelled", "timed-out"}:
                    failed = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="failed", failure_reason=str(error))
                    _record_turn_failed(state, session_id=session.session_id, turn_id=failed.turn_id, provider_id=provider.provider_id, error=str(error))
                    dispatch_source_app_runtime_event(
                        state,
                        session=session,
                        turn=failed,
                        event_type="runtime.turn.failed",
                        failure_reason=str(error),
                    )
            finally:
                release_idle_runtime_processes(state, session_id=session.session_id, provider_id=provider.provider_id, reason="async_turn_idle")

    Thread(target=worker, name=f"maverick-runtime-turn-{turn.turn_id}", daemon=True).start()
    return turn, events



def release_idle_runtime_processes(state: PlatformState, *, session_id: str, provider_id: str, reason: str) -> int:
    """Terminate live provider processes once a runtime session has no pending work."""
    if any(turn.status in _ACTIVE_TURN_STATUSES for turn in state.runtime_store.list_turns(session_id)):
        return 0
    terminated = terminate_runtime_processes(session_id)
    with suppress(Exception):
        _definition, _selection, runtime_adapter = resolve_runtime_backend_for_session(
            state.provider_store,
            session=state.runtime_store.get_session(session_id),
        )
        runtime_adapter.close_runtime(session_id)
    if terminated:
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session_id,
            plane="process",
            event_type="runtime.process.idle_reaped",
            payload={"provider_id": provider_id, "terminated_processes": terminated, "reason": reason},
            event_bus=state.runtime_event_bus,
        )
    return terminated



def interrupt_runtime_provider_turn(
    state: PlatformState,
    session: RuntimeSessionRecord,
    *,
    registry: "ProviderRegistry | None" = None,
) -> bool:
    """Ask the selected runtime provider adapter to interrupt the active turn."""
    with suppress(Exception):
        _definition, _selection, runtime_adapter = resolve_runtime_backend_for_session(
            state.provider_store,
            session=session,
            registry=registry,
        )
        return runtime_adapter.interrupt_turn(session.session_id)
    return False



def _session_execution_lock(session_id: str) -> Lock:
    with _SESSION_EXECUTION_LOCKS_LOCK:
        lock = _SESSION_EXECUTION_LOCKS.get(session_id)
        if lock is None:
            lock = Lock()
            _SESSION_EXECUTION_LOCKS[session_id] = lock
        return lock
