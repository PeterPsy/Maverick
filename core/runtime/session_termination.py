"""Runtime session termination helpers."""

from __future__ import annotations

from uuid import uuid4

from core.runtime.errors import RuntimeSessionNotFoundError, RuntimeTransitionError
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.process_control import terminate_runtime_processes
from core.runtime.service import record_runtime_event, transition_runtime_session, transition_runtime_turn
from core.runtime.store import RuntimeStore


def terminate_runtime_session(
    store: RuntimeStore,
    *,
    session_id: str,
    reason: str,
    event_bus: RuntimeEventBus | None = None,
    observability_store=None,
    start_path=None,
) -> dict[str, object]:
    """Stop live processes and cancel active work for one runtime session."""
    try:
        session = store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return {"session_id": session_id, "found": False, "terminated_processes": 0, "cancelled_turns": 0}

    terminated_processes = terminate_runtime_processes(session_id)
    cancelled_turns = 0
    for turn in store.list_turns(session_id):
        if turn.status in {"queued", "active"}:
            transition_runtime_turn(store, turn_id=turn.turn_id, target_status="cancelled", failure_reason=reason)
            record_runtime_event(
                store,
                event_id=str(uuid4()),
                session_id=session_id,
                turn_id=turn.turn_id,
                plane="turn",
                event_type="runtime.turn.cancelled",
                payload={"reason": reason},
                event_bus=event_bus,
            )
            cancelled_turns += 1

    if session.status in {"running", "stopping"}:
        target_status = "stopped" if session.status == "stopping" else "stopping"
        try:
            session = transition_runtime_session(
                store,
                session_id=session_id,
                target_status=target_status,
                forced_stop_reason=reason,
                observability_store=observability_store,
                start_path=start_path,
            )
            if session.status == "stopping":
                transition_runtime_session(
                    store,
                    session_id=session_id,
                    target_status="stopped",
                    forced_stop_reason=reason,
                    observability_store=observability_store,
                    start_path=start_path,
                )
        except RuntimeTransitionError:
            pass

    return {
        "session_id": session_id,
        "found": True,
        "terminated_processes": terminated_processes,
        "cancelled_turns": cancelled_turns,
    }
