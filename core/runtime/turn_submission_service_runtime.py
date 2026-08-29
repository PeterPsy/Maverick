"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from threading import Event, Lock, Thread, Timer
import time
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.providers.service import resolve_runtime_engine_for_session
from core.runtime.turn_submission_service_events import (
    _complete_turn_from_exit_code,
    _debug_log_runtime_turn,
    _record_final_output,
    _record_turn_failed,
    _terminalize_worker_observed_cancellation,
)
from core.runtime.turn_submission_service_fence import (
    RuntimeTurnQueueFence,
    runtime_turn_queue_fence,
)
from core.runtime.failure_messages import runtime_failure_details
from core.runtime.turn_submission_service_output import (
    _build_launch_spec_for_execution,
    _record_provider_accepted,
    _record_provider_dispatching,
    _record_provider_turn_start_sent,
    _record_turn_activation_completed,
    _record_turn_started,
    _record_turn_thread_availability_active,
    _record_turn_worker_entered,
    _record_turn_worker_started,
)
from core.runtime.agentic_runtime_service import (
    prepare_agentic_runtime,
)
from core.runtime.authority_service import preflight_runtime_context_capabilities, resolve_and_record_runtime_authority
from core.runtime.resolved_runtime_engine import (
    ResolvedRuntimeEngine,
    build_optional_local_launch_spec,
)
from core.runtime.turn_submission_service_output_text import _RuntimeTurnOutputRecorder
from core.runtime.turn_submission_service_queue import _queue_turn_with_event_result
from core.runtime.turn_submission_service_references import (
    _materialize_app_references_for_execution,
    _runtime_app_reference_counts,
)
from core.runtime.plain_hosted_text import (
    HOSTED_TEXT_RUNTIME_PROVIDER_ID,
    assert_plain_hosted_chat_input_allowed,
    execute_plain_hosted_text_turn,
    queue_provider_id_for_session,
    runtime_session_is_plain_hosted_chat,
)
from core.runtime.execution import execute_runtime_turn
from core.runtime.provider_input_context import generalist_orchestration_input_text, runtime_provider_input_sources, runtime_provider_input_text
from core.runtime.provider_start_handoff import (
    patch_runtime_session_metadata,
    provider_thread_recorder,
    runtime_provider_start_handoff,
)
from core.runtime.runtime_process_lifecycle import (
    IDLE_RUNTIME_REAP_TTL_SECONDS,
    interrupt_runtime_provider_turn,
    release_idle_runtime_processes,
)
from core.runtime.client_message_claims import RuntimeClientMessageClaim
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.errors import RuntimeTurnQueueRejectedError
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import record_runtime_event, transition_runtime_turn
from core.runtime.turn_queue_admission import require_turn_queue_session_executable
from core.skills.service import resolve_invoked_runtime_skills

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState

# Retained as a compatibility export through turn_submission_service's facade.
_INTERRUPT_RUNTIME_PROVIDER_TURN_EXPORT = interrupt_runtime_provider_turn


_SESSION_EXECUTION_LOCKS: dict[str, Lock] = {}
_SESSION_EXECUTION_LOCKS_LOCK = Lock()
_IDLE_RUNTIME_REAP_TTL_SECONDS = IDLE_RUNTIME_REAP_TTL_SECONDS
_PREWARM_AFTER_TURN_DELAY_SECONDS = 0.05
_PREWARM_JOIN_TIMEOUT_SECONDS = 0.25
_PREWARM_COMPLETIONS: OrderedDict[str, "_SessionPrewarmState"] = OrderedDict()
_PREWARM_COMPLETIONS_LOCK = Lock()
_PREWARM_STATUS_MAX_ENTRIES = 2048


@dataclass
class _SessionPrewarmState:
    completion: Event
    started_perf_counter: float
    status: str = "pending"
    provider_id: str | None = None
    provider_thread_id: str | None = None
    elapsed_ms: float | None = None
    runtime_ready: bool = False


@dataclass(frozen=True)
class RuntimeSessionPrewarmResult:
    """Redaction-safe readiness state for one runtime session prewarm."""

    status: str
    prewarm_completed: bool
    provider_thread_ready: bool
    runtime_ready: bool = False
    provider_id: str | None = None
    provider_thread_id: str | None = None
    prewarm_total_ms: float | None = None


def _debug_log_runtime_turn_with_timing(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    provider_id: str,
    turn_id: str,
    message: str,
    payload: dict[str, object],
) -> None:
    _debug_log_runtime_turn(
        state,
        session=session,
        provider_id=provider_id,
        turn_id=turn_id,
        message=message,
        payload=payload,
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
        provider_thread_id = ""
        runtime_ready = False
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
                require_turn_queue_session_executable(
                    state.runtime_store,
                    current_session,
                )
                if runtime_session_is_plain_hosted_chat(current_session):
                    status = "skipped_plain_hosted"
                    return
                resolved_engine = ResolvedRuntimeEngine(
                    *resolve_runtime_engine_for_session(
                        state.provider_store,
                        session=current_session,
                        registry=getattr(state, "provider_registry", None),
                    )
                )
                provider_id = resolved_engine.provider_id
                if current_session.provider_id != provider_id:
                    current_session = patch_runtime_session_metadata(
                        state.runtime_store, current_session, provider_id=provider_id
                    )
                launch_result = build_optional_local_launch_spec(
                    resolved_engine,
                    _build_launch_spec_for_execution,
                    state,
                    session=current_session,
                )
                launch_spec = launch_result[0] if isinstance(launch_result, tuple) else launch_result
                if _session_has_executing_turn(state, session.session_id):
                    status = "skipped_active_turn"
                    return

                with runtime_provider_start_handoff(
                    state.runtime_store,
                    session_id=current_session.session_id,
                ) as (provider_session, _provider_accepted):
                    if provider_session.execution_binding is None:
                        legacy_prewarm = getattr(resolved_engine.legacy_adapter, "prewarm_runtime", None)
                        if not callable(legacy_prewarm) or launch_spec is None:
                            status = "legacy_prepare_unavailable"
                            return
                        provider_thread_id = str(legacy_prewarm(provider_session, launch_spec) or "")
                        runtime_ready = bool(provider_thread_id)
                        if provider_thread_id and provider_thread_id != (provider_session.provider_thread_id or ""):
                            provider_thread_recorder(
                                state,
                                session_id=provider_session.session_id,
                                provider_id=provider_id,
                            )(provider_thread_id)
                    else:
                        authority = resolve_and_record_runtime_authority(
                            state,
                            session=provider_session,
                            adapter=resolved_engine.agentic_adapter,
                            turn_id=f"prewarm:{provider_session.session_id}",
                            event_type="runtime.authority.prewarm_evaluated",
                        )
                        prepared = prepare_agentic_runtime(
                            state.runtime_store,
                            session_id=provider_session.session_id,
                            adapter=resolved_engine.agentic_adapter,
                            effective_authority=authority,
                            local_launch_spec=launch_spec,
                        )
                        if not prepared.ready:
                            status = "prepare_not_ready"
                            return
                        runtime_ready = True
                        provider_thread_id = (
                            state.runtime_store.get_provider_state(provider_session.session_id).provider_thread_id or ""
                        )
            finally:
                lock.release()
        except RuntimeTurnQueueRejectedError:
            status = "skipped_session_not_executable"
            return
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
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            _complete_session_prewarm(
                session.session_id,
                completion,
                status=status,
                provider_id=provider_id or None,
                provider_thread_id=provider_thread_id or None,
                runtime_ready=runtime_ready,
                elapsed_ms=elapsed_ms,
            )
            if status != "failed":
                _record_session_prewarm_completed(
                    state,
                    session_id=session.session_id,
                    provider_id=provider_id or None,
                    elapsed_ms=elapsed_ms,
                    status=status,
                    provider_thread_ready=bool(status == "completed" and provider_thread_id),
                    runtime_ready=runtime_ready,
                )

    try:
        Thread(target=worker, name=f"maverick-runtime-prewarm-{session.session_id}", daemon=True).start()
    except Exception as error:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        _record_session_prewarm_failed(
            state,
            session_id=session.session_id,
            provider_id=None,
            elapsed_ms=elapsed_ms,
            error=error,
        )
        _complete_session_prewarm(
            session.session_id,
            completion,
            status="failed",
            elapsed_ms=elapsed_ms,
        )
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
        return any(
            turn.status in {"active", "waiting_for_tool_confirmation"}
            for turn in state.runtime_store.list_turns(session_id)
        )
    return True


def _register_session_prewarm(session_id: str) -> _SessionPrewarmState | None:
    with _PREWARM_COMPLETIONS_LOCK:
        existing = _PREWARM_COMPLETIONS.get(session_id)
        if existing is not None and not existing.completion.is_set():
            return None
        state = _SessionPrewarmState(completion=Event(), started_perf_counter=time.perf_counter())
        _PREWARM_COMPLETIONS[session_id] = state
        _PREWARM_COMPLETIONS.move_to_end(session_id)
        _bound_session_prewarm_states_locked()
        return state


def _complete_session_prewarm(
    session_id: str,
    completion: _SessionPrewarmState,
    *,
    status: str = "completed",
    provider_id: str | None = None,
    provider_thread_id: str | None = None,
    runtime_ready: bool = False,
    elapsed_ms: float | None = None,
) -> None:
    with _PREWARM_COMPLETIONS_LOCK:
        completion.status = status
        completion.provider_id = provider_id
        completion.provider_thread_id = provider_thread_id
        completion.elapsed_ms = elapsed_ms
        completion.runtime_ready = runtime_ready
        completion.completion.set()
        if _PREWARM_COMPLETIONS.get(session_id) is completion:
            _PREWARM_COMPLETIONS.move_to_end(session_id)
        _bound_session_prewarm_states_locked()


def _bound_session_prewarm_states_locked() -> None:
    while len(_PREWARM_COMPLETIONS) > _PREWARM_STATUS_MAX_ENTRIES:
        removable_session_id = next(
            (
                candidate_session_id
                for candidate_session_id, state in _PREWARM_COMPLETIONS.items()
                if state.completion.is_set()
            ),
            None,
        )
        if removable_session_id is None:
            return
        _PREWARM_COMPLETIONS.pop(removable_session_id, None)


def runtime_session_prewarm_status(session_id: str) -> RuntimeSessionPrewarmResult:
    """Return the latest in-process prewarm state for a runtime session."""
    with _PREWARM_COMPLETIONS_LOCK:
        state = _PREWARM_COMPLETIONS.get(session_id)
        if state is None:
            return RuntimeSessionPrewarmResult(
                status="not_started",
                prewarm_completed=False,
                provider_thread_ready=False,
                runtime_ready=False,
            )
        completed = state.completion.is_set()
        status = state.status
        provider_id = state.provider_id
        provider_thread_id = state.provider_thread_id
        runtime_ready = state.runtime_ready
        elapsed_ms = state.elapsed_ms
    return RuntimeSessionPrewarmResult(
        status=status,
        prewarm_completed=completed,
        provider_thread_ready=bool(completed and status == "completed" and provider_thread_id),
        runtime_ready=bool(completed and status == "completed" and runtime_ready),
        provider_id=provider_id,
        provider_thread_id=provider_thread_id,
        prewarm_total_ms=round(elapsed_ms, 3) if elapsed_ms is not None else None,
    )


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
    completed = completion.completion.wait(max(0.0, timeout_seconds))
    elapsed_ms = (time.perf_counter() - wait_started_at) * 1000
    prewarm_total_ms: float | None = None
    prewarm_total_source: str | None = None
    if completed:
        with _PREWARM_COMPLETIONS_LOCK:
            prewarm_total_ms = completion.elapsed_ms
        if prewarm_total_ms is None:
            # Compatibility for callers that only signal the completion event.
            prewarm_total_ms = (time.perf_counter() - completion.started_perf_counter) * 1000
            prewarm_total_source = "elapsed_since_started"
        else:
            prewarm_total_source = "completion_elapsed"
    if state is not None and turn is not None:
        _record_turn_prewarm_waited(
            state,
            session_id=session_id,
            turn_id=turn.turn_id,
            provider_id=provider_id,
            elapsed_ms=elapsed_ms,
            completed=completed,
            timeout_seconds=timeout_seconds,
            prewarm_total_ms=prewarm_total_ms,
            prewarm_total_source=prewarm_total_source,
        )
    return completed


def wait_for_runtime_session_prewarm(session_id: str, *, timeout_seconds: float = _PREWARM_JOIN_TIMEOUT_SECONDS) -> bool:
    """Wait briefly for an in-flight best-effort prewarm without recording turn events."""
    return _wait_for_session_prewarm(session_id, timeout_seconds=timeout_seconds)


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
    provider_thread_ready: bool,
    runtime_ready: bool,
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
                "prewarm_completed": True,
                "provider_thread_ready": provider_thread_ready,
                "runtime_ready": runtime_ready,
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
    prewarm_total_source: str | None,
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
    if prewarm_total_source is not None:
        payload["prewarm_total_source"] = prewarm_total_source
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
    prewarm_total_source: str | None,
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
    if prewarm_total_source is not None:
        payload["prewarm_total_source"] = prewarm_total_source
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
    invoked_skill_ids: list[str] | None = None,
    app_reference_materializer: Callable[[list[dict[str, object]]], object] | None = None,
    on_queued: Callable[[RuntimeTurnRecord, list[RuntimeEventRecord]], None] | None = None,
    turn_id: str | None = None,
    received_perf_counter: float | None = None,
    submission_timing=None,
    client_message_claim: RuntimeClientMessageClaim | None = None,
    queue_fence: RuntimeTurnQueueFence | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    """Queue one runtime turn and execute it in a background worker."""
    plain_hosted = runtime_session_is_plain_hosted_chat(session)
    assert_plain_hosted_chat_input_allowed(
        session,
        attachments=attachments,
        app_references=app_references,
        invoked_skill_ids=invoked_skill_ids,
    )
    invoked_skills = resolve_invoked_runtime_skills(
        session,
        invoked_skill_ids,
        start_path=state.repository_root,
    )
    resolved_turn_id = turn_id or str(uuid4())
    if not plain_hosted:
        preflight_runtime_context_capabilities(
            state,
            session=session,
            turn_id=resolved_turn_id,
            adapter=resolve_runtime_engine_for_session(
                state.provider_store, session=session,
                registry=getattr(state, "provider_registry", None),
            )[2],
            invoked_skills=invoked_skills,
            attachments=attachments,
            app_references=app_references,
        )
    queue_provider_id = HOSTED_TEXT_RUNTIME_PROVIDER_ID if plain_hosted else queue_provider_id_for_session(session)
    with runtime_turn_queue_fence(queue_fence):
        turn, events, created = _queue_turn_with_event_result(
            state,
            session=session,
            input_text=input_text,
            provider_id=queue_provider_id,
            client_message_id=client_message_id,
            attachments=attachments,
            app_references=app_references,
            invoked_skill_ids=[skill.skill_id for skill in invoked_skills],
            turn_id=resolved_turn_id,
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
        worker_metrics: dict[str, float] = {}
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
        lock = _session_execution_lock(session.session_id)
        lock.acquire()
        try:
            worker_metrics["session_lock_wait_ms"] = (time.perf_counter() - lock_wait_started_at) * 1000
            _debug_log_runtime_turn_with_timing(
                state,
                session=session,
                provider_id=worker_provider_id,
                turn_id=turn.turn_id,
                message="Runtime turn debug: async worker entered",
                payload={"phase": "async_worker_entered"},
            )
            try:
                turn_lookup_started_at = time.perf_counter()
                current = state.runtime_store.get_turn(turn.turn_id)
                worker_metrics["worker_turn_lookup_ms"] = (time.perf_counter() - turn_lookup_started_at) * 1000
                if current.status == "cancelled":
                    _debug_log_runtime_turn_with_timing(
                        state,
                        session=session,
                        provider_id=worker_provider_id,
                        turn_id=turn.turn_id,
                        message="Runtime turn debug: async worker saw pre-cancelled turn",
                        payload={"phase": "async_worker_pre_cancelled"},
                    )
                    _terminalize_worker_observed_cancellation(
                        state,
                        turn=current,
                        provider_id=worker_provider_id,
                    )
                    return
                if on_queued is not None:
                    source_app_dispatch_started_at = time.perf_counter()
                    try:
                        on_queued(turn, events)
                    except Exception as error:
                        failure_reason_code, public_error_message = runtime_failure_details(error)
                        failed = transition_runtime_turn(
                            state.runtime_store,
                            turn_id=turn.turn_id,
                            target_status="failed",
                            failure_reason=public_error_message,
                        )
                        if failed.status == "cancelled":
                            _terminalize_worker_observed_cancellation(
                                state,
                                turn=failed,
                                provider_id=worker_provider_id,
                            )
                            return
                        _record_turn_failed(
                            state,
                            session_id=session.session_id,
                            turn_id=failed.turn_id,
                            provider_id=worker_provider_id,
                            error=public_error_message,
                            failure_reason_code=failure_reason_code,
                            diagnostic_reference=f"turn:{failed.turn_id}",
                        )
                        return
                    worker_metrics["source_app_queued_dispatch_ms"] = (time.perf_counter() - source_app_dispatch_started_at) * 1000
                transition_timings: dict[str, float] = {}
                transition_started_at = time.perf_counter()
                active = transition_runtime_turn(
                    state.runtime_store,
                    turn_id=turn.turn_id,
                    target_status="active",
                    timing_payload=transition_timings,
                    update_thread=False,
                )
                if active.status != "active":
                    if active.status == "cancelled":
                        _terminalize_worker_observed_cancellation(
                            state,
                            turn=active,
                            provider_id=worker_provider_id,
                        )
                    return
                transition_active_ms = (time.perf_counter() - transition_started_at) * 1000
                started_event = _record_turn_started(state, session_id=session.session_id, turn_id=active.turn_id, provider_id=worker_provider_id)
                _record_turn_worker_started(
                    state,
                    session_id=session.session_id,
                    turn_id=active.turn_id,
                    provider_id=worker_provider_id,
                    metadata=worker_metrics,
                )
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

                session_lookup_started_at = time.perf_counter()
                current_session = state.runtime_store.get_session(session.session_id)
                current_invoked_skills = resolve_invoked_runtime_skills(
                    current_session,
                    turn.invoked_skill_ids,
                    start_path=state.repository_root,
                )
                worker_metrics["worker_session_lookup_ms"] = (time.perf_counter() - session_lookup_started_at) * 1000
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

                    with runtime_provider_start_handoff(
                        state.runtime_store,
                        session_id=current_session.session_id,
                        turn_id=turn.turn_id,
                        on_provider_accepted=record_plain_provider_accepted,
                    ) as (provider_session, provider_accepted):
                        result, routing_decision = execute_plain_hosted_text_turn(
                            state,
                            session=provider_session,
                            turn_id=turn.turn_id,
                            input_text=generalist_orchestration_input_text(
                                state,
                                session=provider_session,
                                input_text=input_text,
                            ),
                            attachments=attachments,
                            event_sink=output_recorder.record,
                            on_provider_turn_start_sent=record_plain_provider_turn_start_sent,
                            on_provider_accepted=provider_accepted,
                        )
                    worker_provider_id = routing_decision.selected_provider_id or worker_provider_id
                    current_session = patch_runtime_session_metadata(
                        state.runtime_store, current_session, provider_id=worker_provider_id
                    )
                else:
                    resolved_engine = ResolvedRuntimeEngine(
                        *resolve_runtime_engine_for_session(
                            state.provider_store,
                            session=current_session,
                            registry=getattr(state, "provider_registry", None),
                        )
                    )
                    provider = resolved_engine.provider
                    worker_provider_id = resolved_engine.provider_id
                    if current_session.provider_id != worker_provider_id:
                        current_session = patch_runtime_session_metadata(
                            state.runtime_store, current_session, provider_id=worker_provider_id
                        )
                    launch_result = build_optional_local_launch_spec(
                        resolved_engine,
                        _build_launch_spec_for_execution,
                        state,
                        session=current_session,
                        absent_result=(None, {"launch_spec_ms": 0.0, "launch_cache_hit": False}),
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
                    provider_input_text = runtime_provider_input_text(
                        state, session=current_session, input_text=input_text,
                        app_references=execution_app_references,
                        attachments=attachments,
                    )
                    provider_input_sources = runtime_provider_input_sources(
                        state,
                        session=current_session,
                        turn_id=turn.turn_id,
                        input_text=input_text,
                        app_references=execution_app_references,
                        attachments=attachments,
                    )
                    provider_input_metadata = {
                        "provider_input_build_ms": (time.perf_counter() - provider_input_started_at) * 1000,
                        "app_reference_count": app_reference_count,
                        "storage_reference_count": storage_reference_count,
                        "materialized_reference_count": materialized_reference_count,
                    }
                    dispatch_started_at = time.perf_counter()
                    turn_start_sent_at: float | None = None
                    provider_startup_metrics: dict[str, object] = {}
                    provider_startup_started_at: dict[str, float] = {}
                    _record_provider_dispatching(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=worker_provider_id,
                        runtime_mode=current_session.runtime_mode,
                        metadata={**worker_metrics, **provider_input_metadata, **launch_metadata},
                    )

                    def record_provider_startup_event(phase: str, metadata: dict[str, object]) -> None:
                        if phase.endswith("_started"):
                            provider_startup_started_at[phase.removesuffix("_started")] = time.perf_counter()
                        if phase.endswith("_completed"):
                            base_phase = phase.removesuffix("_completed")
                            started_at = provider_startup_started_at.get(base_phase)
                            metric_name = {
                                "ensure_runtime": "ensure_runtime_ms",
                                "remove_generated_skills": "remove_generated_skills_ms",
                                "ensure_thread": "ensure_provider_thread_ms",
                                "event_sink_reset": "event_sink_reset_ms",
                            }.get(base_phase)
                            if metric_name and metric_name not in metadata and started_at is not None:
                                provider_startup_metrics[metric_name] = (time.perf_counter() - started_at) * 1000
                        if phase == "turn_start_write_started":
                            provider_startup_started_at["turn_start_write"] = time.perf_counter()
                        if phase == "turn_start_write_sent":
                            started_at = provider_startup_started_at.get("turn_start_write")
                            if "turn_start_write_ms" not in metadata and started_at is not None:
                                provider_startup_metrics["turn_start_write_ms"] = (time.perf_counter() - started_at) * 1000
                        for key, value in metadata.items():
                            if key.endswith("_ms") and isinstance(value, int | float):
                                provider_startup_metrics[key] = float(value)
                            elif key in {"provider_thread_id", "source"} and value is not None and value != "":
                                provider_startup_metrics[key] = value

                    def record_provider_turn_start_sent(metadata: dict[str, object]) -> None:
                        nonlocal turn_start_sent_at
                        turn_start_sent_at = time.perf_counter()
                        enriched_metadata = {**provider_startup_metrics, **metadata}
                        _record_provider_turn_start_sent(
                            state,
                            session_id=session.session_id,
                            turn_id=turn.turn_id,
                            provider_id=worker_provider_id,
                            runtime_mode=current_session.runtime_mode,
                            metadata=enriched_metadata,
                        )
                        schedule_thread_availability_active_once()

                    def record_provider_accepted(metadata: dict[str, object]) -> None:
                        started_at = turn_start_sent_at if turn_start_sent_at is not None else dispatch_started_at
                        schedule_thread_availability_active_once()
                        enriched_metadata = {**provider_startup_metrics, **metadata}
                        _record_provider_accepted(
                            state,
                            session_id=session.session_id,
                            turn_id=turn.turn_id,
                            provider_id=worker_provider_id,
                            runtime_mode=current_session.runtime_mode,
                            elapsed_ms=(time.perf_counter() - started_at) * 1000,
                            metadata=enriched_metadata,
                        )

                    with runtime_provider_start_handoff(
                        state.runtime_store,
                        session_id=current_session.session_id,
                        turn_id=turn.turn_id,
                        on_provider_accepted=record_provider_accepted,
                    ) as (provider_session, provider_accepted):
                        result = execute_runtime_turn(
                            session=provider_session,
                            provider=provider,
                            input_text=provider_input_text,
                            input_sources=provider_input_sources,
                            invoked_skills=current_invoked_skills,
                            launch_spec=launch_spec,
                            **resolved_engine.execution_kwargs(
                                state, provider_session, correlation_id=turn.turn_id
                            ),
                            on_provider_thread_id=provider_thread_recorder(
                                state,
                                session_id=provider_session.session_id,
                                provider_id=worker_provider_id,
                            ),
                            on_provider_startup_event=record_provider_startup_event,
                            on_provider_turn_start_sent=record_provider_turn_start_sent,
                            on_provider_accepted=provider_accepted,
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
                if current.status == "cancelled" or current.cancellation_requested_at is not None:
                    terminalization = _terminalize_worker_observed_cancellation(
                        state,
                        turn=current,
                        provider_id=worker_provider_id,
                    )
                    current = terminalization.turn
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
                completed_turn, terminal_event = _complete_turn_from_exit_code(
                    state,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    provider_id=worker_provider_id,
                    exit_code=result.exit_code,
                    output_text=app_output_text,
                    failure_reason_code=result.failure_reason_code,
                    public_error_message=result.public_error_message,
                    diagnostic_reference=result.diagnostic_reference,
                )
                if completed_turn.status != "cancelled":
                    dispatch_source_app_runtime_event(
                        state,
                        session=current_session,
                        turn=completed_turn,
                        event_type=terminal_event.event_type,
                        output_text=app_output_text,
                        failure_reason=completed_turn.failure_reason or "",
                        runtime_event_id=terminal_event.event_id,
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
                failure_reason_code, public_error_message = runtime_failure_details(error)
                reason_codes = getattr(error, "reason_codes", None)
                _debug_log_runtime_turn(
                    state,
                    session=session,
                    provider_id=worker_provider_id,
                    turn_id=turn.turn_id,
                    message="Runtime turn debug: async worker raised",
                    payload={
                        "phase": "async_worker_raised",
                        "error_type": type(error).__name__,
                        "error": failure_reason_code,
                    },
                )
                force_idle_reap = not plain_hosted
                current = state.runtime_store.get_turn(turn.turn_id)
                if current.status == "cancelled":
                    _terminalize_worker_observed_cancellation(state, turn=current, provider_id=worker_provider_id)
                    return
                if current.status not in {"completed", "failed", "cancelled", "timed-out"}:
                    failed = transition_runtime_turn(
                        state.runtime_store,
                        turn_id=turn.turn_id,
                        target_status="failed",
                        failure_reason=public_error_message,
                    )
                    if failed.status == "cancelled":
                        _terminalize_worker_observed_cancellation(
                            state,
                            turn=failed,
                            provider_id=worker_provider_id,
                        )
                        return
                    failed_event = _record_turn_failed(
                        state,
                        session_id=session.session_id,
                        turn_id=failed.turn_id,
                        provider_id=worker_provider_id,
                        error=public_error_message,
                        failure_reason_code=failure_reason_code,
                        diagnostic_reference=f"turn:{failed.turn_id}",
                        reason_codes=reason_codes if isinstance(reason_codes, list) else None,
                    )
                    dispatch_source_app_runtime_event(
                        state,
                        session=session,
                        turn=failed,
                        event_type="runtime.turn.failed",
                        failure_reason=public_error_message,
                        runtime_event_id=failed_event.event_id,
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


def _session_execution_lock(session_id: str) -> Lock:
    with _SESSION_EXECUTION_LOCKS_LOCK:
        lock = _SESSION_EXECUTION_LOCKS.get(session_id)
        if lock is None:
            lock = Lock()
            _SESSION_EXECUTION_LOCKS[session_id] = lock
        return lock
