"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace
from threading import Event, Lock, Thread, Timer
import time
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.providers.service import resolve_runtime_backend_for_session
from core.runtime.turn_submission_launch_cache import clear_cached_runtime_launch_context
from core.runtime.turn_submission_service_events import (
    _complete_turn_from_exit_code,
    _debug_log_runtime_turn,
    _record_final_output,
    _record_turn_failed,
)
from core.runtime.turn_submission_service_output import (
    _build_launch_spec_for_execution,
    _record_debug_log_completed,
    _record_app_references_materialize_completed,
    _record_app_references_materialize_failed,
    _record_app_references_materialize_started,
    _record_provider_accepted,
    _record_provider_dispatching,
    _record_provider_input_completed,
    _record_provider_input_started,
    _record_provider_thread_id,
    _record_provider_turn_start_sent,
    _record_session_lock_acquired,
    _record_session_lock_wait_started,
    _record_source_app_queued_dispatch_completed,
    _record_source_app_queued_dispatch_started,
    _record_turn_activation_completed,
    _record_turn_started,
    _record_turn_thread_availability_active,
    _record_turn_worker_entered,
    _record_turn_worker_started,
)
from core.runtime.turn_submission_service_output_text import _RuntimeTurnOutputRecorder
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
_PREWARM_JOIN_TIMEOUT_SECONDS = 2.0
_IDLE_REAP_TIMERS: dict[str, Timer] = {}
_IDLE_REAP_TIMERS_LOCK = Lock()
_PREWARM_COMPLETIONS: dict[str, "_SessionPrewarmState"] = {}
_PREWARM_COMPLETIONS_LOCK = Lock()


@dataclass(frozen=True)
class _SessionPrewarmState:
    completion: Event
    started_perf_counter: float


def _debug_log_runtime_turn_with_timing(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    provider_id: str,
    turn_id: str,
    message: str,
    payload: dict[str, object],
) -> None:
    started_at = time.perf_counter()
    _debug_log_runtime_turn(
        state,
        session=session,
        provider_id=provider_id,
        turn_id=turn_id,
        message=message,
        payload=payload,
    )
    _record_debug_log_completed(
        state,
        session_id=session.session_id,
        turn_id=turn_id,
        provider_id=provider_id,
        phase=str(payload.get("phase") or ""),
        elapsed_ms=(time.perf_counter() - started_at) * 1000,
    )


def prewarm_runtime_session_async(state: PlatformState, *, session: RuntimeSessionRecord) -> None:
    """Best-effort warmup for Codex runtime process and provider thread."""
    if runtime_session_is_plain_hosted_chat(session):
        return
    if _session_has_executing_turn(state, session.session_id):
        return
    completion = _register_session_prewarm(session.session_id)
    if completion is None:
        return
    started_at = time.perf_counter()
    _record_session_prewarm_started(state, session=session)

    def worker() -> None:
        status = "completed"
        provider_id = ""
        try:
            lock = _session_execution_lock(session.session_id)
            if not lock.acquire(blocking=False):
                status = "skipped_lock_busy"
                return
            try:
                if _session_has_executing_turn(state, session.session_id):
                    status = "skipped_active_turn"
                    return
                current_session = state.runtime_store.get_session(session.session_id)
                if runtime_session_is_plain_hosted_chat(current_session):
                    status = "skipped_plain_hosted"
                    return
                provider, selection, runtime_adapter = resolve_runtime_backend_for_session(
                    state.provider_store,
                    session=current_session,
                )
                provider_id = provider.provider_id
                if provider.provider_id != "codex":
                    status = "skipped_non_codex"
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
                if launch_spec is None or _session_has_executing_turn(state, session.session_id):
                    status = "skipped_no_launch_spec"
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
            finally:
                lock.release()
        except Exception as error:
            status = "failed"
            _record_session_prewarm_failed(
                state,
                session_id=session.session_id,
                provider_id=provider_id or None,
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
                error=error,
            )
            return
        finally:
            _complete_session_prewarm(session.session_id, completion)
            if status != "failed":
                _record_session_prewarm_completed(
                    state,
                    session_id=session.session_id,
                    provider_id=provider_id or None,
                    elapsed_ms=(time.perf_counter() - started_at) * 1000,
                    status=status,
                )

    try:
        Thread(target=worker, name=f"maverick-runtime-prewarm-{session.session_id}", daemon=True).start()
    except Exception as error:
        _record_session_prewarm_failed(
            state,
            session_id=session.session_id,
            provider_id=None,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
            error=error,
        )
        _complete_session_prewarm(session.session_id, completion)
        raise


def schedule_runtime_session_prewarm(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    delay_seconds: float = _PREWARM_AFTER_TURN_DELAY_SECONDS,
) -> None:
    """Schedule best-effort prewarm for the next turn after the current worker releases its lock."""
    if runtime_session_is_plain_hosted_chat(session):
        return
    if _session_has_executing_turn(state, session.session_id):
        return

    def run() -> None:
        if _session_has_executing_turn(state, session.session_id):
            return
        with suppress(Exception):
            current_session = state.runtime_store.get_session(session.session_id)
            prewarm_runtime_session_async(state, session=current_session)

    timer = Timer(max(0.0, delay_seconds), run)
    timer.daemon = True
    timer.start()


def _session_has_executing_turn(state: PlatformState, session_id: str) -> bool:
    with suppress(Exception):
        return any(turn.status == "active" for turn in state.runtime_store.list_turns(session_id))
    return True


def _register_session_prewarm(session_id: str) -> _SessionPrewarmState | None:
    with _PREWARM_COMPLETIONS_LOCK:
        existing = _PREWARM_COMPLETIONS.get(session_id)
        if existing is not None and not existing.completion.is_set():
            return None
        state = _SessionPrewarmState(completion=Event(), started_perf_counter=time.perf_counter())
        _PREWARM_COMPLETIONS[session_id] = state
        return state


def _complete_session_prewarm(session_id: str, completion: _SessionPrewarmState) -> None:
    completion.completion.set()
    with _PREWARM_COMPLETIONS_LOCK:
        if _PREWARM_COMPLETIONS.get(session_id) is completion:
            _PREWARM_COMPLETIONS.pop(session_id, None)


def _wait_for_session_prewarm(
    session_id: str,
    *,
    state: PlatformState | None = None,
    turn: RuntimeTurnRecord | None = None,
    provider_id: str | None = None,
    timeout_seconds: float = _PREWARM_JOIN_TIMEOUT_SECONDS,
) -> bool:
    with _PREWARM_COMPLETIONS_LOCK:
        completion = _PREWARM_COMPLETIONS.get(session_id)
    if completion is None:
        return False
    wait_started_at = time.perf_counter()
    if state is not None and turn is not None:
        _record_turn_prewarm_wait_started(
            state,
            session_id=session_id,
            turn_id=turn.turn_id,
            provider_id=provider_id,
            timeout_seconds=timeout_seconds,
        )
    completed = completion.completion.wait(max(0.0, timeout_seconds))
    elapsed_ms = (time.perf_counter() - wait_started_at) * 1000
    prewarm_total_ms = (time.perf_counter() - completion.started_perf_counter) * 1000 if completed else None
    if state is not None and turn is not None:
        _record_turn_prewarm_wait_completed(
            state,
            session_id=session_id,
            turn_id=turn.turn_id,
            provider_id=provider_id,
            elapsed_ms=elapsed_ms,
            completed=completed,
            timeout_seconds=timeout_seconds,
            prewarm_total_ms=prewarm_total_ms,
        )
        _record_turn_prewarm_waited(
            state,
            session_id=session_id,
            turn_id=turn.turn_id,
            provider_id=provider_id,
            elapsed_ms=elapsed_ms,
            completed=completed,
            timeout_seconds=timeout_seconds,
            prewarm_total_ms=prewarm_total_ms,
        )
    return completed


def _record_session_prewarm_started(state: PlatformState, *, session: RuntimeSessionRecord) -> RuntimeEventRecord | None:
    with suppress(Exception):
        return record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            plane="runtime",
            event_type="runtime.prewarm.started",
            payload={
                "provider_id": session.provider_id or "codex",
                "runtime_mode": session.runtime_mode,
            },
            event_bus=getattr(state, "runtime_event_bus", None),
        )
    return None


def _record_session_prewarm_completed(
    state: PlatformState,
    *,
    session_id: str,
    provider_id: str | None,
    elapsed_ms: float,
    status: str,
) -> RuntimeEventRecord | None:
    with suppress(Exception):
        return record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session_id,
            plane="runtime",
            event_type="runtime.prewarm.completed",
            payload={
                "provider_id": provider_id or "codex",
                "prewarm_total_ms": round(elapsed_ms, 3),
                "status": status,
            },
            event_bus=getattr(state, "runtime_event_bus", None),
        )
    return None


def _record_session_prewarm_failed(
    state: PlatformState,
    *,
    session_id: str,
    provider_id: str | None,
    elapsed_ms: float,
    error: Exception,
) -> RuntimeEventRecord | None:
    with suppress(Exception):
        return record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session_id,
            plane="runtime",
            event_type="runtime.prewarm.failed",
            payload={
                "provider_id": provider_id or "codex",
                "prewarm_total_ms": round(elapsed_ms, 3),
                "error_type": error.__class__.__name__,
            },
            event_bus=getattr(state, "runtime_event_bus", None),
        )
    return None


def _record_turn_prewarm_wait_started(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str | None,
    timeout_seconds: float,
) -> RuntimeEventRecord | None:
    payload: dict[str, object] = {
        "provider_id": provider_id or "codex",
        "timeout_seconds": timeout_seconds,
    }
    with suppress(Exception):
        return record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            plane="turn",
            event_type="runtime.turn.prewarm_wait_started",
            payload=payload,
            event_bus=getattr(state, "runtime_event_bus", None),
        )
    return None


def _record_turn_prewarm_wait_completed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str | None,
    elapsed_ms: float,
    completed: bool,
    timeout_seconds: float,
    prewarm_total_ms: float | None,
) -> RuntimeEventRecord | None:
    payload: dict[str, object] = {
        "provider_id": provider_id or "codex",
        "prewarm_wait_ms": round(elapsed_ms, 3),
        "completed": completed,
        "timed_out": not completed,
        "timeout_seconds": timeout_seconds,
    }
    if prewarm_total_ms is not None:
        payload["prewarm_total_ms"] = round(prewarm_total_ms, 3)
    with suppress(Exception):
        return record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            plane="turn",
            event_type="runtime.turn.prewarm_wait_completed",
            payload=payload,
            event_bus=getattr(state, "runtime_event_bus", None),
        )
    return None


def _record_turn_prewarm_waited(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str | None,
    elapsed_ms: float,
    completed: bool,
    timeout_seconds: float,
    prewarm_total_ms: float | None,
) -> RuntimeEventRecord | None:
    payload: dict[str, object] = {
        "provider_id": provider_id or "codex",
        "prewarm_wait_ms": round(elapsed_ms, 3),
        "completed": completed,
        "timed_out": not completed,
        "timeout_seconds": timeout_seconds,
    }
    if prewarm_total_ms is not None:
        payload["prewarm_total_ms"] = round(prewarm_total_ms, 3)
    with suppress(Exception):
        return record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            plane="turn",
            event_type="runtime.turn.prewarm_waited",
            payload=payload,
            event_bus=getattr(state, "runtime_event_bus", None),
        )
    return None


def submit_runtime_turn_async(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    client_message_id: str | None = None,
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    app_reference_materializer: Callable[[list[dict[str, object]]], object] | None = None,
    on_queued: Callable[[RuntimeTurnRecord, list[RuntimeEventRecord]], None] | None = None,
    turn_id: str | None = None,
    received_perf_counter: float | None = None,
    submission_timing=None,
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
        submission_timing=submission_timing,
        client_message_claim=client_message_claim,
    )
    if not created:
        return turn, events

    def worker() -> None:
        _record_turn_worker_entered(
            state,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            provider_id=queue_provider_id,
        )
        force_idle_reap = False
        worker_provider_id = queue_provider_id
        prewarm_after_turn = False
        if not plain_hosted:
            _wait_for_session_prewarm(
                session.session_id,
                state=state,
                turn=turn,
                provider_id=worker_provider_id,
            )
        lock_wait_started_at = time.perf_counter()
        _record_session_lock_wait_started(
            state,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            provider_id=worker_provider_id,
        )
        lock = _session_execution_lock(session.session_id)
        lock.acquire()
        try:
            _record_session_lock_acquired(
                state,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                provider_id=worker_provider_id,
                elapsed_ms=(time.perf_counter() - lock_wait_started_at) * 1000,
            )
            _debug_log_runtime_turn_with_timing(
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
                    _debug_log_runtime_turn_with_timing(
                        state,
                        session=session,
                        provider_id=worker_provider_id,
                        turn_id=turn.turn_id,
                        message="Runtime turn debug: async worker saw pre-cancelled turn",
                        payload={"phase": "async_worker_pre_cancelled"},
                    )
                    return
                if on_queued is not None:
                    source_app_dispatch_started_at = time.perf_counter()
                    _record_source_app_queued_dispatch_started(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=worker_provider_id,
                    )
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
                    _record_source_app_queued_dispatch_completed(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=worker_provider_id,
                        elapsed_ms=(time.perf_counter() - source_app_dispatch_started_at) * 1000,
                    )
                transition_timings: dict[str, float] = {}
                transition_started_at = time.perf_counter()
                active = transition_runtime_turn(
                    state.runtime_store,
                    turn_id=turn.turn_id,
                    target_status="active",
                    timing_payload=transition_timings,
                    update_thread=False,
                )
                transition_active_ms = (time.perf_counter() - transition_started_at) * 1000
                started_event = _record_turn_started(state, session_id=session.session_id, turn_id=active.turn_id, provider_id=worker_provider_id)
                _record_turn_worker_started(state, session_id=session.session_id, turn_id=active.turn_id, provider_id=worker_provider_id)
                _record_turn_activation_completed(
                    state,
                    session_id=session.session_id,
                    turn_id=active.turn_id,
                    provider_id=worker_provider_id,
                    status=active.status,
                    elapsed_ms=transition_active_ms,
                    transition_timings=transition_timings,
                )
                thread_availability_active_scheduled = False

                def schedule_thread_availability_active_once() -> None:
                    nonlocal thread_availability_active_scheduled
                    if thread_availability_active_scheduled:
                        return
                    thread_availability_active_scheduled = True

                    def publish() -> None:
                        with suppress(Exception):
                            current_turn = state.runtime_store.get_turn(active.turn_id)
                            if current_turn.status != "active":
                                return
                            _record_turn_thread_availability_active(
                                state,
                                session_id=session.session_id,
                                turn_id=active.turn_id,
                                provider_id=worker_provider_id,
                                now=started_event.created_at,
                            )

                    Thread(
                        target=publish,
                        name=f"maverick-runtime-thread-active-{active.turn_id}",
                        daemon=True,
                    ).start()

                current_session = state.runtime_store.get_session(session.session_id)
                _debug_log_runtime_turn_with_timing(
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
                        schedule_thread_availability_active_once()

                    def record_plain_provider_accepted(metadata: dict[str, object]) -> None:
                        selected_provider_id = str(metadata.get("provider_id") or worker_provider_id)
                        started_at = turn_start_sent_at if turn_start_sent_at is not None else dispatch_started_at
                        schedule_thread_availability_active_once()
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
                    app_reference_count, storage_reference_count = _runtime_app_reference_counts(app_references)
                    execution_app_references = _materialize_app_references_for_execution(
                        app_references=app_references,
                        app_reference_materializer=app_reference_materializer,
                        state=state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=worker_provider_id,
                    )
                    materialized_reference_count = len([item for item in execution_app_references or [] if isinstance(item, dict)])
                    provider_input_started_at = time.perf_counter()
                    _record_provider_input_started(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=worker_provider_id,
                        app_reference_count=app_reference_count,
                        storage_reference_count=storage_reference_count,
                        materialized_reference_count=materialized_reference_count,
                    )
                    provider_input_text = input_text_with_attachment_links(
                        input_text=input_text_with_app_references(input_text=input_text, app_references=execution_app_references),
                        attachments=attachments,
                        workspace_root=current_session.workspace_root,
                    )
                    _record_provider_input_completed(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=worker_provider_id,
                        elapsed_ms=(time.perf_counter() - provider_input_started_at) * 1000,
                        app_reference_count=app_reference_count,
                        storage_reference_count=storage_reference_count,
                        materialized_reference_count=materialized_reference_count,
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
                        schedule_thread_availability_active_once()

                    def record_provider_accepted(metadata: dict[str, object]) -> None:
                        started_at = turn_start_sent_at if turn_start_sent_at is not None else dispatch_started_at
                        schedule_thread_availability_active_once()
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
        finally:
            lock.release()
        if prewarm_after_turn:
            schedule_runtime_session_prewarm(state, session=session)

    Thread(target=worker, name=f"maverick-runtime-turn-{turn.turn_id}", daemon=True).start()
    return turn, events


def _materialize_app_references_for_execution(
    *,
    app_references: list[dict[str, object]] | None,
    app_reference_materializer: Callable[[list[dict[str, object]]], object] | None,
    state: PlatformState | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    provider_id: str | None = None,
) -> list[dict[str, object]] | None:
    references = [item for item in app_references or [] if isinstance(item, dict)]
    if not references or app_reference_materializer is None:
        return references
    app_reference_count, storage_reference_count = _runtime_app_reference_counts(references)
    can_record = state is not None and session_id is not None and turn_id is not None and provider_id is not None
    if can_record:
        _record_app_references_materialize_started(
            state,
            session_id=session_id,
            turn_id=turn_id,
            provider_id=provider_id,
            app_reference_count=app_reference_count,
            storage_reference_count=storage_reference_count,
        )
    started_at = time.perf_counter()
    try:
        raw_materialized = app_reference_materializer(references)
        materialized, reference_action_timings, reference_cache_hit = _coerce_materialized_reference_result(raw_materialized)
    except Exception as error:
        reference_action_timings = _materializer_reference_action_timings(locals().get("raw_materialized"))
        if can_record:
            _record_app_references_materialize_failed(
                state,
                session_id=session_id,
                turn_id=turn_id,
                provider_id=provider_id,
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
                app_reference_count=app_reference_count,
                storage_reference_count=storage_reference_count,
                error=error,
                reference_action_timings=reference_action_timings,
            )
        raise
    materialized_references = [item for item in materialized or [] if isinstance(item, dict)]
    if can_record:
        _record_app_references_materialize_completed(
            state,
            session_id=session_id,
            turn_id=turn_id,
            provider_id=provider_id,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
            app_reference_count=app_reference_count,
            storage_reference_count=storage_reference_count,
            materialized_reference_count=len(materialized_references),
            reference_cache_hit=reference_cache_hit,
            reference_action_timings=reference_action_timings,
        )
    return materialized_references


def _coerce_materialized_reference_result(raw_result: object) -> tuple[list[dict[str, object]], list[dict[str, object]], bool]:
    references = getattr(raw_result, "references", raw_result)
    timings = _materializer_reference_action_timings(raw_result)
    cache_hit = bool(getattr(raw_result, "reference_cache_hit", False))
    if not isinstance(references, list):
        return [], timings, cache_hit
    return [item for item in references if isinstance(item, dict)], timings, cache_hit


def _materializer_reference_action_timings(raw_result: object) -> list[dict[str, object]]:
    timings = getattr(raw_result, "reference_action_timings", None)
    if not isinstance(timings, list):
        return []
    return [item for item in timings if isinstance(item, dict)]


def _runtime_app_reference_counts(references: list[dict[str, object]] | None) -> tuple[int, int]:
    items = [item for item in references or [] if isinstance(item, dict)]
    storage_count = sum(1 for item in items if str(item.get("app_id") or "").strip().lower() == "storage")
    return len(items), storage_count



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
    clear_cached_runtime_launch_context(session_id)
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
