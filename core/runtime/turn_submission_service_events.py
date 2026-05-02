"""Runtime turn submission helpers shared by HTTP and future host surfaces."""

from __future__ import annotations

from contextlib import suppress
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from core.observability.service import append_platform_log
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import record_runtime_event, transition_runtime_turn
from core.runtime.thread_catalog_events import set_thread_availability

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.providers.provider_registry import ProviderRegistry


_SESSION_EXECUTION_LOCKS: dict[str, Lock] = {}
_SESSION_EXECUTION_LOCKS_LOCK = Lock()
_ACTIVE_TURN_STATUSES = {"queued", "active"}


def _record_final_output(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    output_text: str,
    exit_code: int,
) -> RuntimeEventRecord:
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.output.final",
        payload={"text": output_text, "provider_id": provider_id, "exit_code": exit_code},
        event_bus=state.runtime_event_bus,
    )



def _complete_turn_from_exit_code(
    state: PlatformState,
    *,
    session_id: str,
    turn_id: str,
    provider_id: str,
    exit_code: int,
) -> tuple[RuntimeTurnRecord, RuntimeEventRecord]:
    if exit_code == 0:
        turn = transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="completed")
        event_type = "runtime.turn.completed"
    else:
        turn = transition_runtime_turn(
            state.runtime_store,
            turn_id=turn_id,
            target_status="failed",
            failure_reason=f"Provider exited with code {exit_code}.",
        )
        event_type = "runtime.turn.failed"
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type=event_type,
        payload={"provider_id": provider_id, "exit_code": exit_code},
        event_bus=state.runtime_event_bus,
    )
    set_thread_availability(
        state,
        workspace_id=turn.workspace_id,
        runtime_session_id=session_id,
        availability="free",
        now=event.created_at,
    )
    return turn, event



def _record_turn_failed(state: PlatformState, *, session_id: str, turn_id: str, provider_id: str, error: str) -> RuntimeEventRecord:
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        plane="turn",
        event_type="runtime.turn.failed",
        payload={"error": error, "provider_id": provider_id},
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
