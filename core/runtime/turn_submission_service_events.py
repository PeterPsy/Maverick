"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from contextlib import suppress
import os
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.observability.service import append_platform_log
from core.runtime.errors import RuntimeTurnNotFoundError
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.failure_messages import (
    normalized_failure_reason_code,
    runtime_failure_public_message,
)
from core.runtime.service import record_runtime_event, transition_runtime_turn
from core.runtime.thread_catalog_events import mark_thread_response_completed, set_thread_availability
from core.runtime.turn_terminalization import (
    RuntimeTurnTerminalizationResult,
    terminalize_runtime_turn_cancellation,
)

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.providers.provider_registry import ProviderRegistry


_SESSION_EXECUTION_LOCKS: dict[str, Lock] = {}
_SESSION_EXECUTION_LOCKS_LOCK = Lock()
_ACTIVE_TURN_STATUSES = {"queued", "active", "waiting_for_tool_confirmation"}


def _record_final_output(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    output_text: str,
    complete_text: str,
    exit_code: int,
) -> RuntimeEventRecord:
    try:
        existing = state.runtime_store.find_turn_event(
            turn_id=turn_id,
            event_type="runtime.output.final",
        )
    except RuntimeTurnNotFoundError:
        existing = None
    if existing is not None and isinstance(existing.payload.get("delivery_id"), str):
        # Submission lifecycle events identify the runtime engine. The hosted
        # durable final outbox identifies the model provider instead. Resolve
        # that namespace from the persisted pin, never from the emitted payload.
        binding = state.runtime_store.get_session(session_id).execution_binding
        expected_provider_id = provider_id
        if (
            binding is not None
            and binding.execution_family == "maverick_agent"
            and provider_id == binding.runtime_engine_id
        ):
            expected_provider_id = binding.model_provider_id
        if (
            existing.session_id != session_id
            or existing.payload.get("complete_text") != complete_text
            or existing.payload.get("provider_id") != expected_provider_id
            or existing.payload.get("exit_code") != exit_code
        ):
            raise RuntimeError("runtime_final_output_identity_conflict")
        return existing
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.output.final",
        payload={
            "text": output_text,
            "complete_text": complete_text,
            "provider_id": provider_id,
            "exit_code": exit_code,
        },
        event_bus=state.runtime_event_bus,
    )



def _complete_turn_from_exit_code(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    exit_code: int,
    output_text: str = "",
    failure_reason_code: str | None = None,
    public_error_message: str | None = None,
    diagnostic_reference: str | None = None,
) -> tuple[RuntimeTurnRecord, RuntimeEventRecord]:
    reason_code = None
    public_message = None
    if exit_code == 0:
        turn = transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="completed")
    else:
        reason_code = normalized_failure_reason_code(
            failure_reason_code,
            fallback="provider_execution_failed",
        )
        mapped_message = runtime_failure_public_message(reason_code)
        public_message = (
            str(public_error_message).strip()
            if isinstance(public_error_message, str)
            and 0 < len(public_error_message.strip()) <= 512
            and public_error_message.strip() == mapped_message
            else mapped_message
        )
        turn = transition_runtime_turn(
            state.runtime_store,
            turn_id=turn_id,
            target_status="failed",
            failure_reason=public_message,
        )
    if turn.status == "cancelled":
        terminalization = _terminalize_worker_observed_cancellation(
            state,
            turn=turn,
            provider_id=provider_id,
            exit_code=exit_code,
            output_text=output_text,
        )
        if terminalization.event is None:
            raise RuntimeError(f"Cancelled runtime turn `{turn.turn_id}` has no terminal event.")
        return terminalization.turn, terminalization.event
    event_type = f"runtime.turn.{turn.status}"
    payload: dict[str, object] = {
        "provider_id": provider_id,
        "exit_code": exit_code,
        **({"reason": turn.failure_reason or "Runtime turn cancelled."} if turn.status == "cancelled" else {}),
    }
    if turn.status == "failed":
        payload.update(
            {
                "error": public_message or runtime_failure_public_message(reason_code),
                "failure_reason_code": reason_code or "provider_execution_failed",
            }
        )
        if _safe_diagnostic_reference(diagnostic_reference) is not None:
            payload["diagnostic_reference"] = diagnostic_reference
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type=event_type,
        payload=payload,
        event_bus=state.runtime_event_bus,
    )
    if turn.status == "completed":
        mark_thread_response_completed(
            state,
            workspace_id=turn.workspace_id,
            runtime_session_id=session_id,
            turn_id=turn.turn_id,
            now=event.created_at,
        )
    else:
        set_thread_availability(
            state,
            workspace_id=turn.workspace_id,
            runtime_session_id=session_id,
            availability="free",
            now=event.created_at,
        )
    return turn, event


def _terminalize_worker_observed_cancellation(
    state: PlatformState,
    *,
    turn: RuntimeTurnRecord,
    provider_id: str,
    exit_code: int | None = None,
    output_text: str = "",
) -> RuntimeTurnTerminalizationResult:
    """Drain the authoritative cancellation outbox when a turn worker loses the race."""
    reason = turn.cancellation_reason or turn.failure_reason or "Runtime turn cancelled."
    event_payload: dict[str, object] = {
        "provider_id": provider_id,
        "reason": reason,
    }
    if exit_code is not None:
        event_payload["exit_code"] = exit_code
    return terminalize_runtime_turn_cancellation(
        state.runtime_store,
        turn_id=turn.turn_id,
        reason=reason,
        event_payload=event_payload,
        event_bus=state.runtime_event_bus,
        callback=lambda session, cancelled_turn, event: dispatch_source_app_runtime_event(
            state,
            session=session,
            turn=cancelled_turn,
            event_type=event.event_type,
            output_text=output_text,
            failure_reason=reason,
            runtime_event_id=event.event_id,
            raise_on_failure=True,
            start_path=getattr(state, "repository_root", None),
        ),
        request_intent=False,
    )


def _record_turn_failed(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    error: str,
    failure_reason_code: str | None = None,
    diagnostic_reference: str | None = None,
    reason_codes: list[str] | None = None,
) -> RuntimeEventRecord:
    reason_code = normalized_failure_reason_code(
        failure_reason_code or error,
        fallback="runtime_execution_failed",
    )
    payload = {
        "error": runtime_failure_public_message(reason_code),
        "failure_reason_code": reason_code,
        "provider_id": provider_id,
    }
    if _safe_diagnostic_reference(diagnostic_reference) is not None:
        payload["diagnostic_reference"] = diagnostic_reference
    if reason_codes:
        safe_reason_codes = [
            normalized_failure_reason_code(value, fallback="")
            for value in reason_codes[:32]
        ]
        safe_reason_codes = list(
            dict.fromkeys(value for value in safe_reason_codes if value)
        )
        if safe_reason_codes:
            payload["reason_codes"] = safe_reason_codes
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.failed",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )
    turn = state.runtime_store.get_turn(turn_id)
    set_thread_availability(
        state,
        workspace_id=turn.workspace_id,
        runtime_session_id=session_id,
        availability="free",
        now=event.created_at,
    )
    return event


def _safe_diagnostic_reference(value: object) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        return None
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:._-")
    return value if all(character in allowed for character in value) else None



def _debug_log_runtime_turn(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    provider_id: str,
    turn_id: str,
    message: str,
    payload: dict[str, object],
) -> None:
    """Write best-effort runtime turn diagnostics without changing execution behavior."""
    if not _runtime_turn_debug_logs_enabled():
        return
    with suppress(Exception):
        append_platform_log(
            log_plane="runtime",
            message=message,
            payload={
                "component": "runtime_turn_submission",
                "session_id": session.session_id,
                "turn_id": turn_id,
                **payload,
            },
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            provider_id=provider_id,
            start_path=state.repository_root,
        )


def _runtime_turn_debug_logs_enabled() -> bool:
    return os.environ.get("MAVERICK_RUNTIME_TURN_DEBUG_LOGS", "").strip().lower() in {"1", "true", "yes", "on"}
