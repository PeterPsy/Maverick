"""Runtime session, turn, event, and process lifecycle helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from core.runtime.runtime_events import RuntimeEventPlane, RuntimeEventRecord
from core.runtime.runtime_process import RuntimeProcessRecord, RuntimeProcessStatus
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
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    event = RuntimeEventRecord(
        event_id=event_id,
        workspace_id=session.workspace_id,
        session_id=session_id,
        plane=plane,
        event_type=event_type,
        turn_id=turn_id,
        process_id=process_id,
        payload=payload,
        created_at=timestamp,
    )
    saved = store.save_event(event)
    if event_bus is not None:
        event_bus.publish(saved)
    return saved



def create_runtime_process(
    store: RuntimeStore,
    *,
    process_id: str,
    session_id: str,
    command: list[str],
    cwd: str | None = None,
    now: datetime | None = None,
) -> RuntimeProcessRecord:
    """Create one local runtime process handle record."""
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    return store.save_process(
        RuntimeProcessRecord(
            process_id=process_id,
            session_id=session_id,
            workspace_id=session.workspace_id,
            status="created",
            command=command,
            cwd=cwd or session.workdir,
            stdin_open=False,
            stdout_open=False,
            exit_code=None,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=None,
            ended_at=None,
            failure_reason=None,
        )
    )



def transition_runtime_process(
    store: RuntimeStore,
    *,
    process_id: str,
    target_status: RuntimeProcessStatus,
    exit_code: int | None = None,
    failure_reason: str | None = None,
    stdin_open: bool | None = None,
    stdout_open: bool | None = None,
    now: datetime | None = None,
) -> RuntimeProcessRecord:
    """Transition one runtime process handle between canonical states."""
    timestamp = now or utcnow()
    process = store.get_process(process_id)
    allowed: dict[RuntimeProcessStatus, set[RuntimeProcessStatus]] = {
        "created": {"running", "failed", "terminated"},
        "running": {"exited", "failed", "terminated", "timed-out"},
        "exited": set(),
        "failed": set(),
        "terminated": set(),
        "timed-out": set(),
    }
    _transition_allowed(process.status, target_status, allowed=allowed, kind="runtime process")
    return store.save_process(
        replace(
            process,
            status=target_status,
            stdin_open=stdin_open if stdin_open is not None else process.stdin_open,
            stdout_open=stdout_open if stdout_open is not None else process.stdout_open,
            exit_code=exit_code,
            updated_at=timestamp,
            started_at=process.started_at or (timestamp if target_status == "running" else None),
            ended_at=timestamp if target_status in {"exited", "failed", "terminated", "timed-out"} else None,
            failure_reason=failure_reason,
        )
    )
