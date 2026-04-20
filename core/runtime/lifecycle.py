"""Runtime session, turn, event, and process lifecycle helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.observability.service import append_platform_log, record_platform_audit, record_platform_event
from core.runtime.errors import RuntimeTransitionError
from core.runtime.routing import build_runtime_routing
from core.runtime.runtime_events import RuntimeEventPlane, RuntimeEventRecord
from core.runtime.runtime_process import RuntimeProcessRecord, RuntimeProcessStatus
from core.runtime.runtime_session import RuntimeSessionRecord, RuntimeSessionStatus
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_turns import RuntimeTurnRecord, RuntimeTurnStatus
from core.runtime.store import RuntimeStore
from core.workspaces.models import WorkspaceGovernanceRecord

if TYPE_CHECKING:
    from core.runtime.event_bus import RuntimeEventBus


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _transition_allowed(current: str, target: str, *, allowed: dict[str, set[str]], kind: str) -> None:
    if target not in allowed[current]:
        raise RuntimeTransitionError(f"Cannot transition {kind} from `{current}` to `{target}`.")


def create_runtime_session(
    store: RuntimeStore,
    *,
    session_id: str,
    workspace_id: str,
    agent_id: str,
    requested_mode: str | None = None,
    system_prompt: str | None = None,
    skill_ids: list[str] | None = None,
    source_app_id: str | None = None,
    governance: WorkspaceGovernanceRecord | None = None,
    platform_allows_full_access: bool = False,
    now: datetime | None = None,
    start_path: Path | None = None,
    observability_store=None,
) -> RuntimeSessionRecord:
    """Create one runtime session and its initial runtime state."""
    timestamp = now or utcnow()
    routing = build_runtime_routing(
        workspace_id=workspace_id,
        agent_id=agent_id,
        requested_mode=requested_mode,
        governance=governance,
        platform_allows_full_access=platform_allows_full_access,
        start_path=start_path,
    )
    session = RuntimeSessionRecord(
        session_id=session_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        status="created",
        requested_mode=routing.requested_mode,
        effective_mode=routing.effective_mode,
        workspace_root=routing.workspace_root,
        workdir=routing.workdir,
        runtime_root=routing.runtime_root,
        started_at=None,
        updated_at=timestamp,
        ended_at=None,
        last_progress_at=None,
        system_prompt=system_prompt.strip() if isinstance(system_prompt, str) and system_prompt.strip() else None,
        skill_ids=[str(skill_id).strip() for skill_id in (skill_ids or []) if str(skill_id).strip()],
        source_app_id=source_app_id.strip() if isinstance(source_app_id, str) and source_app_id.strip() else None,
    )
    state = RuntimeStateRecord(
        session_id=session_id,
        workspace_id=workspace_id,
        current_turn_id=None,
        session_status="created",
        turn_status=None,
        last_progress_at=None,
        watchdog_deadline_at=None,
        forced_stop_reason=None,
        last_error_detail=None,
        updated_at=timestamp,
    )
    store.save_state(state)
    saved = store.save_session(session)
    if observability_store is not None:
        payload = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "requested_mode": routing.requested_mode,
            "effective_mode": routing.effective_mode,
        }
        record_platform_event(
            observability_store,
            event_type="runtime.session.created",
            event_plane="runtime",
            source_domain="runtime",
            workspace_id=workspace_id,
            runtime_session_id=session_id,
            payload=payload,
            now=timestamp,
        )
        record_platform_audit(
            observability_store,
            action="runtime.session.create",
            status="succeeded",
            source_domain="runtime",
            detail=f"Created runtime session `{session_id}` for workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            runtime_session_id=session_id,
            payload=payload,
            now=timestamp,
        )
        append_platform_log(
            log_plane="runtime",
            message=f"Created runtime session `{session_id}`.",
            payload=payload,
            workspace_id=workspace_id,
            runtime_session_id=session_id,
            start_path=start_path,
            now=timestamp,
        )
    return saved


def create_child_runtime_session(
    store: RuntimeStore,
    *,
    parent_session_id: str,
    child_session_id: str,
    child_agent_id: str,
    now: datetime | None = None,
) -> RuntimeSessionRecord:
    """Create one runtime child session that reuses the parent's resolved boundary only."""
    parent = store.get_session(parent_session_id)
    timestamp = now or utcnow()
    session = RuntimeSessionRecord(
        session_id=child_session_id,
        workspace_id=parent.workspace_id,
        agent_id=child_agent_id,
        status="created",
        requested_mode=parent.requested_mode,
        effective_mode=parent.effective_mode,
        workspace_root=parent.workspace_root,
        workdir=parent.workdir,
        runtime_root=parent.runtime_root,
        started_at=None,
        updated_at=timestamp,
        ended_at=None,
        last_progress_at=None,
        system_prompt=parent.system_prompt,
        skill_ids=list(parent.skill_ids),
        source_app_id=parent.source_app_id,
    )
    state = RuntimeStateRecord(
        session_id=child_session_id,
        workspace_id=parent.workspace_id,
        current_turn_id=None,
        session_status="created",
        turn_status=None,
        last_progress_at=None,
        watchdog_deadline_at=None,
        forced_stop_reason=None,
        last_error_detail=None,
        updated_at=timestamp,
    )
    store.save_state(state)
    return store.save_session(session)


def transition_runtime_session(
    store: RuntimeStore,
    *,
    session_id: str,
    target_status: RuntimeSessionStatus,
    error_detail: str | None = None,
    forced_stop_reason: str | None = None,
    now: datetime | None = None,
    observability_store=None,
    start_path: Path | None = None,
) -> RuntimeSessionRecord:
    """Transition one runtime session between canonical lifecycle statuses."""
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    allowed: dict[RuntimeSessionStatus, set[RuntimeSessionStatus]] = {
        "created": {"running", "failed"},
        "running": {"stopping", "stopped", "failed"},
        "stopping": {"stopped", "failed", "running"},
        "stopped": {"running"},
        "failed": {"running"},
    }
    _transition_allowed(session.status, target_status, allowed=allowed, kind="runtime session")
    started_at = session.started_at or (timestamp if target_status == "running" else None)
    ended_at = timestamp if target_status in {"stopped", "failed"} else None
    updated = replace(
        session,
        status=target_status,
        started_at=started_at,
        updated_at=timestamp,
        ended_at=ended_at,
        last_progress_at=timestamp if target_status == "running" else session.last_progress_at,
    )
    state = store.get_state(session_id)
    store.save_state(
        replace(
            state,
            session_status=target_status,
            last_progress_at=timestamp if target_status == "running" else state.last_progress_at,
            forced_stop_reason=forced_stop_reason or state.forced_stop_reason,
            last_error_detail=error_detail or state.last_error_detail,
            updated_at=timestamp,
        )
    )
    saved = store.save_session(updated)
    if observability_store is not None:
        payload = {
            "session_id": session_id,
            "from_status": session.status,
            "to_status": target_status,
            "forced_stop_reason": forced_stop_reason,
            "error_detail": error_detail,
        }
        audit_status = "failed" if target_status == "failed" else "succeeded"
        record_platform_event(
            observability_store,
            event_type="runtime.session.transitioned",
            event_plane="runtime",
            source_domain="runtime",
            workspace_id=session.workspace_id,
            runtime_session_id=session_id,
            payload=payload,
            now=timestamp,
        )
        record_platform_audit(
            observability_store,
            action="runtime.session.transition",
            status=audit_status,
            source_domain="runtime",
            detail=f"Transitioned runtime session `{session_id}` from `{session.status}` to `{target_status}`.",
            workspace_id=session.workspace_id,
            runtime_session_id=session_id,
            payload=payload,
            now=timestamp,
        )
        append_platform_log(
            log_plane="runtime",
            message=f"Runtime session `{session_id}` transitioned to `{target_status}`.",
            payload=payload,
            workspace_id=session.workspace_id,
            runtime_session_id=session_id,
            start_path=start_path,
            now=timestamp,
        )
    return saved


def reconcile_runtime_session_policy(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
    *,
    governance: WorkspaceGovernanceRecord | None = None,
    platform_allows_full_access: bool = False,
    now: datetime | None = None,
    start_path: Path | None = None,
) -> RuntimeSessionRecord:
    """Bring a persisted runtime session back in line with current execution policy."""
    timestamp = now or utcnow()
    routing = build_runtime_routing(
        workspace_id=session.workspace_id,
        agent_id=session.agent_id,
        requested_mode=session.requested_mode,
        governance=governance,
        platform_allows_full_access=platform_allows_full_access,
        start_path=start_path,
    )
    if (
        session.effective_mode == routing.effective_mode
        and session.workspace_root == routing.workspace_root
        and session.workdir == routing.workdir
        and session.runtime_root == routing.runtime_root
    ):
        return session
    reconciled = replace(
        session,
        effective_mode=routing.effective_mode,
        workspace_root=routing.workspace_root,
        workdir=routing.workdir,
        runtime_root=routing.runtime_root,
        updated_at=timestamp,
    )
    return store.save_session(reconciled)


def queue_runtime_turn(
    store: RuntimeStore,
    *,
    turn_id: str,
    session_id: str,
    input_text: str | None = None,
    now: datetime | None = None,
) -> RuntimeTurnRecord:
    """Create one queued runtime turn."""
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    return store.save_turn(
        RuntimeTurnRecord(
            turn_id=turn_id,
            session_id=session_id,
            workspace_id=session.workspace_id,
            status="queued",
            input_text=input_text,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=None,
            completed_at=None,
            failure_reason=None,
        )
    )


def transition_runtime_turn(
    store: RuntimeStore,
    *,
    turn_id: str,
    target_status: RuntimeTurnStatus,
    failure_reason: str | None = None,
    now: datetime | None = None,
) -> RuntimeTurnRecord:
    """Transition one runtime turn between canonical lifecycle statuses."""
    timestamp = now or utcnow()
    turn = store.get_turn(turn_id)
    allowed: dict[RuntimeTurnStatus, set[RuntimeTurnStatus]] = {
        "queued": {"active", "cancelled", "timed-out"},
        "active": {"completed", "failed", "cancelled", "timed-out"},
        "completed": set(),
        "failed": set(),
        "cancelled": set(),
        "timed-out": set(),
    }
    _transition_allowed(turn.status, target_status, allowed=allowed, kind="runtime turn")
    updated = replace(
        turn,
        status=target_status,
        updated_at=timestamp,
        started_at=turn.started_at or (timestamp if target_status == "active" else None),
        completed_at=timestamp if target_status in {"completed", "failed", "cancelled", "timed-out"} else None,
        failure_reason=failure_reason,
    )
    state = store.get_state(turn.session_id)
    store.save_state(
        replace(
            state,
            current_turn_id=turn.turn_id if target_status == "active" else None,
            turn_status=target_status if target_status == "active" else None,
            last_progress_at=timestamp,
            last_error_detail=failure_reason if target_status in {"failed", "timed-out"} else state.last_error_detail,
            updated_at=timestamp,
        )
    )
    session = store.get_session(turn.session_id)
    store.save_session(replace(session, last_progress_at=timestamp, updated_at=timestamp))
    return store.save_turn(updated)


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
