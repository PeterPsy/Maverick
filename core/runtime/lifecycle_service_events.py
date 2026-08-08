"""Runtime lifecycle event recording."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.lifecycle_service_sessions import utcnow
from core.runtime.output_compaction import ToolOutputCompactionContext, compact_tool_call_event
from core.runtime.runtime_events import RuntimeEventPlane, RuntimeEventRecord
from core.runtime.store import RuntimeStore

if TYPE_CHECKING:
    from core.runtime.event_bus import RuntimeEventBus


def record_runtime_event(
    store: RuntimeStore,
    *,
    event_id: str,
    session_id: str,
    plane: RuntimeEventPlane,
    event_type: str,
    payload: dict,
    turn_id: str | None = None,
    process_id: str | None = None,
    now: datetime | None = None,
    event_bus: "RuntimeEventBus | None" = None,
) -> RuntimeEventRecord:
    """Persist one structured runtime-domain event."""
    event = _runtime_event_record(
        store,
        event_id=event_id,
        session_id=session_id,
        plane=plane,
        event_type=event_type,
        payload=payload,
        turn_id=turn_id,
        process_id=process_id,
        now=now,
    )
    saved = store.save_event(event)
    if event_bus is not None:
        event_bus.publish(saved)
    return saved


def record_runtime_turn_event_once(
    store: RuntimeStore,
    *,
    event_id: str,
    session_id: str,
    turn_id: str,
    event_type: str,
    payload: dict,
    now: datetime | None = None,
    event_bus: "RuntimeEventBus | None" = None,
) -> tuple[RuntimeEventRecord, bool]:
    """Atomically publish at most one event for one turn and terminal type."""
    event = _runtime_event_record(
        store,
        event_id=event_id,
        session_id=session_id,
        plane="turn",
        event_type=event_type,
        payload=payload,
        turn_id=turn_id,
        process_id=None,
        now=now,
    )
    saved, inserted = store.save_turn_event_if_absent(event)
    if inserted and event_bus is not None:
        event_bus.publish(saved)
    return saved, inserted


def _runtime_event_record(
    store: RuntimeStore,
    *,
    event_id: str,
    session_id: str,
    plane: RuntimeEventPlane,
    event_type: str,
    payload: dict,
    turn_id: str | None,
    process_id: str | None,
    now: datetime | None,
) -> RuntimeEventRecord:
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    compacted_payload = _compacted_runtime_event_payload(
        event_type=event_type,
        plane=plane,
        payload=payload,
        session_id=session_id,
        turn_id=turn_id,
    )
    return RuntimeEventRecord(
        event_id=event_id,
        workspace_id=session.workspace_id,
        session_id=session_id,
        plane=plane,
        event_type=event_type,
        turn_id=turn_id,
        process_id=process_id,
        payload=compacted_payload,
        created_at=timestamp,
    )


def _compacted_runtime_event_payload(
    *,
    event_type: str,
    plane: RuntimeEventPlane,
    payload: dict,
    session_id: str,
    turn_id: str | None,
) -> dict:
    if not event_type.startswith("runtime.tool_call."):
        return payload
    event = compact_tool_call_event(
        RuntimeExecutionEvent(event_type=event_type, payload=payload, plane=plane),
        context=ToolOutputCompactionContext(session_id=session_id, turn_id=turn_id),
    )
    return event.payload
