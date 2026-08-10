"""Runtime session termination helpers."""

from __future__ import annotations

from core.runtime.errors import RuntimeSessionNotFoundError, RuntimeTransitionError
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.process_control import terminate_runtime_processes
from core.runtime.service import transition_runtime_session
from core.runtime.store import RuntimeStore
from core.runtime.turn_terminalization import terminalize_runtime_turn_cancellation
from core.runtime.turn_submission_launch_cache import clear_cached_runtime_launch_context


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

    clear_cached_runtime_launch_context(session_id)
    terminated_processes = terminate_runtime_processes(session_id)
    cancelled_turns = 0
    for turn in store.list_turns(session_id):
        if turn.status in {"queued", "active"}:
            terminalization = terminalize_runtime_turn_cancellation(
                store,
                turn_id=turn.turn_id,
                reason=reason,
                event_payload={"reason": reason},
                event_bus=event_bus,
            )
            if terminalization.turn.status == "cancelled" and terminalization.claimed:
                cancelled_turns += 1

    if session.status in {"created", "running", "stopping"}:
        target_status = "stopped" if session.status in {"created", "stopping"} else "stopping"
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
