"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from threading import Lock, Thread, Timer
import time
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.providers.service import resolve_runtime_backend_for_session
from core.runtime.turn_submission_service_output import _build_launch_spec_for_execution, _record_provider_thread_id
from core.runtime.plain_hosted_text import (
    HOSTED_TEXT_RUNTIME_PROVIDER_ID,
    assert_plain_hosted_chat_input_allowed,
    execute_plain_hosted_text_turn,
    queue_provider_id_for_session,
    runtime_session_is_plain_hosted_chat,
)
from core.runtime.app_references import input_text_with_app_references
from core.runtime.attachments import input_text_with_attachment_links
from core.runtime.execution import execute_runtime_turn
from core.runtime.process_control import terminate_codex_app_server_processes_for_session, terminate_runtime_processes
from core.runtime.client_message_claims import RuntimeClientMessageClaim
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
_IDLE_RUNTIME_REAP_TTL_SECONDS = 180.0
_PREWARM_AFTER_TURN_DELAY_SECONDS = 0.05
_IDLE_REAP_TIMERS: dict[str, Timer] = {}
_IDLE_REAP_TIMERS_LOCK = Lock()


def prewarm_runtime_session_async(state: PlatformState, *, session: RuntimeSessionRecord) -> None:
    """Best-effort warmup for Codex runtime process and provider thread."""
    if runtime_session_is_plain_hosted_chat(session):
        return
    if not _session_has_any_turn(state, session.session_id):
        return
    if _session_has_active_turn(state, session.session_id):
        return

    def worker() -> None:
        lock = _session_execution_lock(session.session_id)
        if not lock.acquire(blocking=False):
            return
        try:
            if _session_has_active_turn(state, session.session_id):
                return
            current_session = state.runtime_store.get_session(session.session_id)
            if runtime_session_is_plain_hosted_chat(current_session):
                return
            provider, selection, runtime_adapter = resolve_runtime_backend_for_session(
                state.provider_store,
                session=current_session,
            )
            if provider.provider_id != "codex":
                return
            if current_session.provider_id != provider.provider_id:
                current_session = state.runtime_store.save_session(replace(current_session, provider_id=provider.provider_id))
            launch_spec, _metadata = _build_launch_spec_for_execution(
                state,
                session=current_session,
                provider_id=provider.provider_id,
                provider_definition=provider,
                provider_selection=selection,
                runtime_adapter=runtime_adapter,
            )
            if launch_spec is None or _session_has_active_turn(state, session.session_id):
                return
            from core.providers.codex_app_server import prewarm_codex_app_server_runtime

            provider_thread_id = prewarm_codex_app_server_runtime(
                session=current_session,
                launch_spec=launch_spec,
            )
            if provider_thread_id and provider_thread_id != (current_session.provider_thread_id or ""):
                _record_provider_thread_id(
                    state,
                    session=current_session,
                    provider_id=provider.provider_id,
                    provider_thread_id=provider_thread_id,
                )
        except Exception:
            return
        finally:
            lock.release()

    Thread(target=worker, name=f"maverick-runtime-prewarm-{session.session_id}", daemon=True).start()


def schedule_runtime_session_prewarm(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    delay_seconds: float = _PREWARM_AFTER_TURN_DELAY_SECONDS,
) -> None:
    """Schedule best-effort prewarm for the next turn after the current worker releases its lock."""
    if runtime_session_is_plain_hosted_chat(session):
        return
    if _session_has_active_turn(state, session.session_id):
        return

    def run() -> None:
        if _session_has_active_turn(state, session.session_id):
            return
        with suppress(Exception):
            current_session = state.runtime_store.get_session(session.session_id)
            prewarm_runtime_session_async(state, session=current_session)

    timer = Timer(max(0.0, delay_seconds), run)
    timer.daemon = True
    timer.start()


def _session_has_any_turn(state: PlatformState, session_id: str) -> bool:
    with suppress(Exception):
        return bool(state.runtime_store.list_turns(session_id))
    return False


def _session_has_active_turn(state: PlatformState, session_id: str) -> bool:
    with suppress(Exception):
        return any(turn.status in _ACTIVE_TURN_STATUSES for turn in state.runtime_store.list_turns(session_id))
    return True


def submit_runtime_turn_async(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    client_message_id: str | None = None,
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    app_reference_materializer: Callable[[list[dict[str, object]]], list[dict[str, object]]] | None = None,
    on_queued: Callable[[RuntimeTurnRecord, list[RuntimeEventRecord]], None] | None = None,
    turn_id: str | None = None,
    received_perf_counter: float | None = None,
    client_message_claim: RuntimeClientMessageClaim | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    """Queue one runtime turn and execute it in a background worker."""
    plain_hosted = runtime_session_is_plain_hosted_chat(session)
    assert_plain_hosted_chat_input_allowed(session, attachments=attachments, app_references=app_references)
    queue_provider_id = HOSTED_TEXT_RUNTIME_PROVIDER_ID if plain_hosted else queue_provider_id_for_session(session)
    turn, events, created = _queue_turn_with_event_result(
        state,
        session=session,
        input_text=input_text,
        provider_id=queue_provider_id,
        client_message_id=client_message_id,
        attachments=attachments,
        app_references=app_references,
        turn_id=turn_id,
        received_perf_counter=received_perf_counter,
        client_message_claim=client_message_claim,
    )
    if not created:
        return turn, events

    def worker() -> None:
        force_idle_reap = False
        worker_provider_id = queue_provider_id
        prewarm_after_turn = False
        with _session_execution_lock(session.session_id):
            _debug_log_runtime_turn(
                state,
                session=session,
                provider_id=worker_provider_id,
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
                        provider_id=worker_provider_id,
                        turn_id=turn.turn_id,
                        message="Runtime turn debug: async worker saw pre-cancelled turn",
                        payload={"phase": "async_worker_pre_cancelled"},
                    )
                    return
                if on_queued is not None:
                    try:
                        on_queued(turn, events)
                    except Exception as error:
                        failed = transition_runtime_turn(
                            state.runtime_store,
                            turn_id=turn.turn_id,
                            target_status="failed",
                            failure_reason=str(error),
                        )
                        _record_turn_failed(
                            state,
                            session_id=session.session_id,
                            turn_id=failed.turn_id,
                            provider_id=worker_provider_id,
                            error=str(error),
                        )
                        return
                active = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")
                _record_turn_started(state, session_id=session.session_id, turn_id=active.turn_id, provider_id=worker_provider_id)
                _record_turn_worker_started(state, session_id=session.session_id, turn_id=active.turn_id, provider_id=worker_provider_id)
                current_session = state.runtime_store.get_session(session.session_id)
                _debug_log_runtime_turn(
                    state,
                    session=current_session,
                    provider_id=worker_provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async execution started",
                    payload={"phase": "async_execution_started", "turn_status": active.status},
                )
                output_recorder = _RuntimeTurnOutputRecorder(state, session_id=session.session_id, turn_id=turn.turn_id)
                if runtime_session_is_plain_hosted_chat(current_session):
                    dispatch_started_at = time.perf_counter()
                    turn_start_sent_at: float | None = None
                    _record_provider_dispatching(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=worker_provider_id,
                        runtime_mode=current_session.runtime_mode,
                    )

                    def record_plain_provider_turn_start_sent(metadata: dict[str, object]) -> None:
                        nonlocal turn_start_sent_at
                        turn_start_sent_at = time.perf_counter()
                        selected_provider_id = str(metadata.get("provider_id") or worker_provider_id)
                        _record_provider_turn_start_sent(
                            state,
                            session_id=session.session_id,
                            turn_id=turn.turn_id,
                            provider_id=selected_provider_id,
                            runtime_mode=current_session.runtime_mode,
                            metadata=metadata,
                        )

                    def record_plain_provider_accepted(metadata: dict[str, object]) -> None:
                        selected_provider_id = str(metadata.get("provider_id") or worker_provider_id)
                        started_at = turn_start_sent_at if turn_start_sent_at is not None else dispatch_started_at
                        _record_provider_accepted(
                            state,
                            session_id=session.session_id,
                            turn_id=turn.turn_id,
                            provider_id=selected_provider_id,
                            runtime_mode=current_session.runtime_mode,
                            elapsed_ms=(time.perf_counter() - started_at) * 1000,
                            metadata=metadata,
                        )

                    result, routing_decision = execute_plain_hosted_text_turn(
                        state,
                        session=current_session,
                        turn_id=turn.turn_id,
                        input_text=input_text,
                        attachments=attachments,
                        event_sink=output_recorder.record,
                        on_provider_turn_start_sent=record_plain_provider_turn_start_sent,
                        on_provider_accepted=record_plain_provider_accepted,
                    )
                    worker_provider_id = routing_decision.selected_provider_id or worker_provider_id
                    current_session = state.runtime_store.save_session(replace(current_session, provider_id=worker_provider_id))
                else:
                    provider, selection, runtime_adapter = resolve_runtime_backend_for_session(state.provider_store, session=current_session)
                    worker_provider_id = provider.provider_id
                    if current_session.provider_id != worker_provider_id:
                        current_session = state.runtime_store.save_session(replace(current_session, provider_id=worker_provider_id))
                    launch_result = _build_launch_spec_for_execution(
                        state,
                        session=current_session,
                        provider_id=worker_provider_id,
                        provider_definition=provider,
                        provider_selection=selection,
                        runtime_adapter=runtime_adapter,
                    )
                    if isinstance(launch_result, tuple):
                        launch_spec, launch_metadata = launch_result
                    else:
                        launch_spec, launch_metadata = launch_result, {}
                    execution_app_references = _materialize_app_references_for_execution(
                        app_references=app_references,
                        app_reference_materializer=app_reference_materializer,
                    )
                    provider_input_text = input_text_with_attachment_links(
                        input_text=input_text_with_app_references(input_text=input_text, app_references=execution_app_references),
                        attachments=attachments,
                        workspace_root=current_session.workspace_root,
                    )
                    dispatch_started_at = time.perf_counter()
                    turn_start_sent_at: float | None = None
                    _record_provider_dispatching(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=worker_provider_id,
                        runtime_mode=current_session.runtime_mode,
                        metadata=launch_metadata,
                    )

                    def record_provider_turn_start_sent(metadata: dict[str, object]) -> None:
                        nonlocal turn_start_sent_at
                        turn_start_sent_at = time.perf_counter()
                        _record_provider_turn_start_sent(
                            state,
                            session_id=session.session_id,
                            turn_id=turn.turn_id,
                            provider_id=worker_provider_id,
                            runtime_mode=current_session.runtime_mode,
                            metadata=metadata,
                        )

                    def record_provider_accepted(metadata: dict[str, object]) -> None:
                        started_at = turn_start_sent_at if turn_start_sent_at is not None else dispatch_started_at
                        _record_provider_accepted(
                            state,
                            session_id=session.session_id,
                            turn_id=turn.turn_id,
                            provider_id=worker_provider_id,
                            runtime_mode=current_session.runtime_mode,
                            elapsed_ms=(time.perf_counter() - started_at) * 1000,
                            metadata=metadata,
                        )

                    result = execute_runtime_turn(
                        session=current_session,
                        provider=provider,
                        input_text=provider_input_text,
                        launch_spec=launch_spec,
                        runtime_adapter=runtime_adapter,
                        on_provider_thread_id=lambda provider_thread_id: _record_provider_thread_id(
                            state,
                            session=current_session,
                            provider_id=worker_provider_id,
                            provider_thread_id=provider_thread_id,
                        ),
                        on_provider_turn_start_sent=record_provider_turn_start_sent,
                        on_provider_accepted=record_provider_accepted,
                        event_sink=output_recorder.record,
                    )
                _debug_log_runtime_turn(
                    state,
                    session=current_session,
                    provider_id=worker_provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async execution returned",
                    payload={"phase": "async_execution_returned", "exit_code": result.exit_code, "output_text_length": len(result.output_text)},
                )
                current = state.runtime_store.get_turn(turn.turn_id)
                if current.status == "cancelled":
                    _debug_log_runtime_turn(
                        state,
                        session=current_session,
                        provider_id=worker_provider_id,
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
                    provider_id=worker_provider_id,
                    output_text=final_output_text,
                    complete_text=app_output_text,
                    exit_code=result.exit_code,
                )
                completed_turn, terminal_event = _complete_turn_from_exit_code(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=worker_provider_id, exit_code=result.exit_code)
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
                    provider_id=worker_provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async terminal event recorded",
                    payload={"phase": "async_terminal_event_recorded", "turn_status": completed_turn.status, "terminal_event_type": terminal_event.event_type},
                )
                prewarm_after_turn = not plain_hosted
            except Exception as error:
                failure_reason = str(getattr(error, "reason_code", None) or error)
                reason_codes = getattr(error, "reason_codes", None)
                _debug_log_runtime_turn(
                    state,
                    session=session,
                    provider_id=worker_provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async worker raised",
                    payload={"phase": "async_worker_raised", "error_type": type(error).__name__, "error": failure_reason},
                )
                force_idle_reap = not plain_hosted
                current = state.runtime_store.get_turn(turn.turn_id)
                if current.status not in {"completed", "failed", "cancelled", "timed-out"}:
                    failed = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="failed", failure_reason=failure_reason)
                    _record_turn_failed(
                        state,
                        session_id=session.session_id,
                        turn_id=failed.turn_id,
                        provider_id=worker_provider_id,
                        error=failure_reason,
                        reason_codes=reason_codes if isinstance(reason_codes, list) else None,
                    )
                    dispatch_source_app_runtime_event(
                        state,
                        session=session,
                        turn=failed,
                        event_type="runtime.turn.failed",
                        failure_reason=failure_reason,
                    )
            finally:
                if not plain_hosted:
                    release_idle_runtime_processes(
                        state,
                        session_id=session.session_id,
                        provider_id=worker_provider_id,
                        reason="async_turn_failed" if force_idle_reap else "async_turn_idle",
                        idle_ttl_seconds=0 if force_idle_reap else None,
                    )
        if prewarm_after_turn:
            schedule_runtime_session_prewarm(state, session=session)

    Thread(target=worker, name=f"maverick-runtime-turn-{turn.turn_id}", daemon=True).start()
    return turn, events


def _materialize_app_references_for_execution(
    *,
    app_references: list[dict[str, object]] | None,
    app_reference_materializer: Callable[[list[dict[str, object]]], list[dict[str, object]]] | None,
) -> list[dict[str, object]] | None:
    references = [item for item in app_references or [] if isinstance(item, dict)]
    if not references or app_reference_materializer is None:
        return references
    return app_reference_materializer(references)



def release_idle_runtime_processes(
    state: PlatformState,
    *,
    session_id: str,
    provider_id: str,
    reason: str,
    idle_ttl_seconds: float | None = _IDLE_RUNTIME_REAP_TTL_SECONDS,
) -> int:
    """Terminate live provider processes after an idle TTL when a session has no pending work."""
    if any(turn.status in _ACTIVE_TURN_STATUSES for turn in state.runtime_store.list_turns(session_id)):
        return 0
    if idle_ttl_seconds is None:
        idle_ttl_seconds = _IDLE_RUNTIME_REAP_TTL_SECONDS
    if idle_ttl_seconds > 0:
        return _schedule_idle_runtime_process_reap(
            state,
            session_id=session_id,
            provider_id=provider_id,
            reason=reason,
            idle_ttl_seconds=idle_ttl_seconds,
        )
    _cancel_scheduled_idle_runtime_process_reap(session_id)
    terminated = terminate_runtime_processes(session_id)
    with suppress(Exception):
        _definition, _selection, runtime_adapter = resolve_runtime_backend_for_session(
            state.provider_store,
            session=state.runtime_store.get_session(session_id),
        )
        closed = runtime_adapter.close_runtime(session_id)
        if isinstance(closed, int):
            terminated += closed
    if provider_id == "codex":
        terminated += terminate_codex_app_server_processes_for_session(session_id)
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


def _schedule_idle_runtime_process_reap(
    state: PlatformState,
    *,
    session_id: str,
    provider_id: str,
    reason: str,
    idle_ttl_seconds: float,
) -> int:
    key = session_id

    def run_reap() -> None:
        with _IDLE_REAP_TIMERS_LOCK:
            if _IDLE_REAP_TIMERS.get(key) is not timer:
                return
            _IDLE_REAP_TIMERS.pop(key, None)
        release_idle_runtime_processes(
            state,
            session_id=session_id,
            provider_id=provider_id,
            reason=reason,
            idle_ttl_seconds=0,
        )

    timer = Timer(idle_ttl_seconds, run_reap)
    timer.daemon = True
    with _IDLE_REAP_TIMERS_LOCK:
        previous = _IDLE_REAP_TIMERS.get(key)
        _IDLE_REAP_TIMERS[key] = timer
    if previous is not None:
        previous.cancel()
    timer.start()
    return 0


def _cancel_scheduled_idle_runtime_process_reap(session_id: str) -> None:
    with _IDLE_REAP_TIMERS_LOCK:
        timer = _IDLE_REAP_TIMERS.pop(session_id, None)
    if timer is not None:
        timer.cancel()



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
