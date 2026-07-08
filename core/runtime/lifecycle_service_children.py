"""Runtime session, turn, event, and process lifecycle helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.observability.service import append_platform_log, record_platform_audit, record_platform_event
from core.runtime.client_message_claims import RuntimeClientMessageClaim
from core.runtime.routing import build_runtime_routing
from core.runtime.runtime_session import RuntimeSessionRecord, RuntimeSessionStatus
from core.runtime.runtime_turns import RuntimeTurnRecord, RuntimeTurnStatus
from core.runtime.runtime_threads import (
    mark_runtime_thread_response_completed,
    mark_runtime_thread_user_message,
    runtime_thread_availability_for_session,
    update_runtime_thread_availability,
)
from core.runtime.store import RuntimeStore
from core.workspaces.models import WorkspaceGovernanceRecord

if TYPE_CHECKING:
    from core.runtime.event_bus import RuntimeEventBus


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
        "created": {"running", "stopped", "failed"},
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
        session_id=session.session_id,
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
    client_message_id: str | None = None,
    now: datetime | None = None,
) -> RuntimeTurnRecord:
    """Create one queued runtime turn."""
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    record = store.save_turn(
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
            runtime_mode=session.runtime_mode,
            client_message_id=client_message_id.strip() if isinstance(client_message_id, str) and client_message_id.strip() else None,
        )
    )
    _update_thread_for_queued_turn(store, record)
    return record


def queue_runtime_turn_if_client_message_absent(
    store: RuntimeStore,
    *,
    turn_id: str,
    session_id: str,
    input_text: str | None = None,
    client_message_id: str | None = None,
    client_message_claim: RuntimeClientMessageClaim | None = None,
    now: datetime | None = None,
) -> tuple[RuntimeTurnRecord, bool]:
    """Create one queued runtime turn unless the client message was already queued."""
    timestamp = now or utcnow()
    session = store.get_session(session_id)
    record = RuntimeTurnRecord(
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
        runtime_mode=session.runtime_mode,
        client_message_id=client_message_id.strip() if isinstance(client_message_id, str) and client_message_id.strip() else None,
    )
    save_claimed = getattr(store, "save_turn_if_current_client_message_claim", None)
    if client_message_claim is not None and callable(save_claimed):
        turn, created = save_claimed(record, client_message_claim, now=timestamp)
        if created:
            _update_thread_for_queued_turn(store, turn)
        return turn, created
    save_once = getattr(store, "save_turn_if_client_message_absent", None)
    if callable(save_once):
        turn, created = save_once(record)
        if created:
            _update_thread_for_queued_turn(store, turn)
        return turn, created
    store.save_turn(record)
    _update_thread_for_queued_turn(store, record)
    return record, True



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
        "queued": {"active", "failed", "cancelled", "timed-out"},
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
    saved = store.save_turn(updated)
    _update_thread_for_turn_transition(store, saved)
    return saved


def _update_thread_for_queued_turn(store: RuntimeStore, turn: RuntimeTurnRecord) -> None:
    mark_runtime_thread_user_message(
        store,
        workspace_id=turn.workspace_id,
        runtime_session_id=turn.session_id,
        input_text=turn.input_text or "",
        now=turn.created_at,
    )


def _update_thread_for_turn_transition(store: RuntimeStore, turn: RuntimeTurnRecord) -> None:
    if turn.status == "completed":
        mark_runtime_thread_response_completed(
            store,
            workspace_id=turn.workspace_id,
            runtime_session_id=turn.session_id,
            turn_id=turn.turn_id,
            now=turn.completed_at or turn.updated_at,
        )
        return
    availability = runtime_thread_availability_for_session(store, runtime_session_id=turn.session_id)
    update_runtime_thread_availability(
        store,
        workspace_id=turn.workspace_id,
        runtime_session_id=turn.session_id,
        availability=availability,
        now=turn.updated_at,
    )
