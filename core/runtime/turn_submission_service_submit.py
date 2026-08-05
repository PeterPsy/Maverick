"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from threading import Lock
import time
from typing import TYPE_CHECKING, Callable

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.providers.service import resolve_runtime_backend_for_session
from core.runtime.plain_hosted_text import (
    HOSTED_TEXT_RUNTIME_PROVIDER_ID,
    assert_plain_hosted_chat_input_allowed,
    runtime_session_is_plain_hosted_chat,
)
from core.runtime.client_message_claims import RuntimeClientMessageClaim
from core.runtime.execution import execute_runtime_turn
from core.runtime.provider_input_context import runtime_provider_input_text
from core.runtime.provider_start_handoff import (
    provider_thread_recorder,
    runtime_provider_start_handoff,
)
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import transition_runtime_turn
from core.runtime.turn_submission_service_events import (
    _complete_turn_from_exit_code,
    _debug_log_runtime_turn,
    _record_final_output,
    _record_turn_failed,
)
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
from core.runtime.turn_submission_service_output_text import _RuntimeTurnOutputRecorder
from core.runtime.turn_submission_service_references import (
    _materialize_app_references_for_execution,
    _runtime_app_reference_counts,
)
from core.runtime.turn_submission_service_sync_hosted import execute_sync_plain_hosted_turn
from core.runtime.turn_submission_service_runtime import _wait_for_session_prewarm

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
    app_reference_materializer: Callable[[list[dict[str, object]]], object] | None = None,
    on_queued: Callable[[RuntimeTurnRecord, list[RuntimeEventRecord]], None] | None = None,
    turn_id: str | None = None,
    received_perf_counter: float | None = None,
    submission_timing=None,
    client_message_claim: RuntimeClientMessageClaim | None = None,
    queue_fence: RuntimeTurnQueueFence | None = None,
) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    """Queue and execute one runtime turn synchronously."""
    plain_hosted = runtime_session_is_plain_hosted_chat(session)
    assert_plain_hosted_chat_input_allowed(session, attachments=attachments, app_references=app_references)
    if plain_hosted:
        provider = None
        runtime_adapter = None
        provider_id = HOSTED_TEXT_RUNTIME_PROVIDER_ID
    else:
        provider, selection, runtime_adapter = resolve_runtime_backend_for_session(state.provider_store, session=session)
        provider_id = provider.provider_id
    with runtime_turn_queue_fence(queue_fence):
        turn, events, created = _queue_turn_with_event_result(
            state,
            session=session,
            input_text=input_text,
            provider_id=provider_id,
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
    events.append(_record_turn_worker_entered(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider_id))
    worker_metrics: dict[str, float] = {}
    if on_queued is not None:
        source_app_dispatch_started_at = time.perf_counter()
        try:
            on_queued(turn, events)
        except Exception as error:
            failed = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="failed", failure_reason=str(error))
            _record_turn_failed(state, session_id=session.session_id, turn_id=failed.turn_id, provider_id=provider_id, error=str(error))
            raise
        worker_metrics["source_app_queued_dispatch_ms"] = (time.perf_counter() - source_app_dispatch_started_at) * 1000
    if not plain_hosted:
        _wait_for_session_prewarm(
            session.session_id,
            state=state,
            turn=turn,
            provider_id=provider_id,
        )
    lock_wait_started_at = time.perf_counter()
    lock = _session_execution_lock(session.session_id)
    lock.acquire()
    try:
        worker_metrics["session_lock_wait_ms"] = (time.perf_counter() - lock_wait_started_at) * 1000
        try:
            turn = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")
            started_event = _record_turn_started(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider_id)
            events.append(started_event)
            events.append(
                _record_turn_worker_started(
                    state,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    provider_id=provider_id,
                    metadata=worker_metrics,
                )
            )
            events.extend(
                _record_turn_thread_availability_active(
                    state,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    provider_id=provider_id,
                    now=started_event.created_at,
                )
            )
            events.append(
                _record_turn_activation_completed(
                    state,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    provider_id=provider_id,
                    status=turn.status,
                )
            )
            _debug_log_runtime_turn(
                state,
                session=session,
                provider_id=provider_id,
                turn_id=turn.turn_id,
                message="Runtime turn debug: sync execution started",
                payload={"phase": "sync_execution_started", "turn_status": turn.status},
            )
            output_recorder = _RuntimeTurnOutputRecorder(state, session_id=session.session_id, turn_id=turn.turn_id)
            if plain_hosted:
                result, provider_id, session = execute_sync_plain_hosted_turn(
                    state,
                    session=session,
                    turn=turn,
                    input_text=input_text,
                    attachments=attachments,
                    output_recorder=output_recorder,
                    provider_id=provider_id,
                    events=events,
                )
            else:
                assert provider is not None
                launch_result = _build_launch_spec_for_execution(
                    state,
                    session=session,
                    provider_id=provider_id,
                    provider_definition=provider,
                    provider_selection=selection,
                    runtime_adapter=runtime_adapter,
                )
                launch_spec = launch_result[0] if isinstance(launch_result, tuple) else launch_result
                app_reference_count, storage_reference_count = _runtime_app_reference_counts(app_references)
                execution_app_references = _materialize_app_references_for_execution(
                    app_references=app_references,
                    app_reference_materializer=app_reference_materializer,
                    state=state,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    provider_id=provider_id,
                )
                materialized_reference_count = len([item for item in execution_app_references or [] if isinstance(item, dict)])
                provider_input_started_at = time.perf_counter()
                provider_input_text = runtime_provider_input_text(
                    state, session=session, input_text=input_text,
                    app_references=execution_app_references, attachments=attachments,
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
                events.append(
                    _record_provider_dispatching(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=provider_id,
                        runtime_mode=session.runtime_mode,
                        metadata={**worker_metrics, **provider_input_metadata},
                    )
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
                    sent = _record_provider_turn_start_sent(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=provider_id,
                        runtime_mode=session.runtime_mode,
                        metadata=enriched_metadata,
                    )
                    events.append(sent)

                def record_provider_accepted(metadata: dict[str, object]) -> None:
                    started_at = turn_start_sent_at if turn_start_sent_at is not None else dispatch_started_at
                    enriched_metadata = {**provider_startup_metrics, **metadata}
                    accepted = _record_provider_accepted(
                        state,
                        session_id=session.session_id,
                        turn_id=turn.turn_id,
                        provider_id=provider_id,
                        runtime_mode=session.runtime_mode,
                        elapsed_ms=(time.perf_counter() - started_at) * 1000,
                        metadata=enriched_metadata,
                    )
                    events.append(accepted)

                with runtime_provider_start_handoff(
                    state.runtime_store,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    on_provider_accepted=record_provider_accepted,
                ) as (provider_session, provider_accepted):
                    result = execute_runtime_turn(
                        session=provider_session,
                        provider=provider,
                        input_text=provider_input_text,
                        launch_spec=launch_spec,
                        runtime_adapter=runtime_adapter,
                        on_provider_thread_id=provider_thread_recorder(
                            state,
                            session_id=provider_session.session_id,
                            provider_id=provider_id,
                        ),
                        on_provider_startup_event=record_provider_startup_event,
                        on_provider_turn_start_sent=record_provider_turn_start_sent,
                        on_provider_accepted=provider_accepted,
                        event_sink=output_recorder.record,
                    )
        except Exception as error:
            failure_reason = str(getattr(error, "reason_code", None) or error)
            reason_codes = getattr(error, "reason_codes", None)
            _debug_log_runtime_turn(
                state,
                session=session,
                provider_id=provider_id,
                turn_id=turn.turn_id,
                message="Runtime turn debug: sync execution raised",
                payload={"phase": "sync_execution_raised", "error_type": type(error).__name__, "error": failure_reason},
            )
            current = state.runtime_store.get_turn(turn.turn_id)
            if current.status in {"completed", "failed", "cancelled", "timed-out"}:
                return current, events
            turn = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="failed", failure_reason=failure_reason)
            events.append(
                _record_turn_failed(
                    state,
                    session_id=session.session_id,
                    turn_id=turn.turn_id,
                    provider_id=provider_id,
                    error=failure_reason,
                    reason_codes=reason_codes if isinstance(reason_codes, list) else None,
                )
            )
            dispatch_source_app_runtime_event(
                state,
                session=session,
                turn=turn,
                event_type="runtime.turn.failed",
                failure_reason=failure_reason,
            )
            if not plain_hosted:
                release_idle_runtime_processes(state, session_id=session.session_id, provider_id=provider_id, reason="sync_turn_failed", idle_ttl_seconds=0)
            return turn, events
        current = state.runtime_store.get_turn(turn.turn_id)
        if current.status in {"completed", "failed", "cancelled", "timed-out"}:
            return current, events
        _debug_log_runtime_turn(
            state,
            session=session,
            provider_id=provider_id,
            turn_id=turn.turn_id,
            message="Runtime turn debug: sync execution returned",
            payload={"phase": "sync_execution_returned", "exit_code": result.exit_code, "output_text_length": len(result.output_text)},
        )
        final_output_text = output_recorder.final_text(result.output_text)
        app_output_text = output_recorder.complete_text(result.output_text)
        events.append(
            _record_final_output(
                state,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                provider_id=provider_id,
                output_text=final_output_text,
                complete_text=app_output_text,
                exit_code=result.exit_code,
            )
        )
        turn, terminal_event = _complete_turn_from_exit_code(state, session_id=session.session_id, turn_id=turn.turn_id, provider_id=provider_id, exit_code=result.exit_code)
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
            provider_id=provider_id,
            turn_id=turn.turn_id,
            message="Runtime turn debug: sync terminal event recorded",
            payload={"phase": "sync_terminal_event_recorded", "turn_status": turn.status, "terminal_event_type": terminal_event.event_type},
        )
        if not plain_hosted:
            release_idle_runtime_processes(state, session_id=session.session_id, provider_id=provider_id, reason="sync_turn_terminal")
        return turn, events
    finally:
        lock.release()
