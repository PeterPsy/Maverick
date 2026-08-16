"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from contextlib import suppress
import os
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.observability.service import append_platform_log
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
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
) -> tuple[RuntimeTurnRecord, RuntimeEventRecord]:
    if exit_code == 0:
        turn = transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="completed")
    else:
        turn = transition_runtime_turn(
            state.runtime_store,
            turn_id=turn_id,
            target_status="failed",
            failure_reason=f"Provider exited with code {exit_code}.",
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
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type=event_type,
        payload={
            "provider_id": provider_id,
            "exit_code": exit_code,
            **({"reason": turn.failure_reason or "Runtime turn cancelled."} if turn.status == "cancelled" else {}),
        },
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
    reason_codes: list[str] | None = None,
) -> RuntimeEventRecord:
    payload = {"error": error, "provider_id": provider_id}
    if reason_codes:
        payload["reason_codes"] = list(dict.fromkeys(reason_codes))
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
