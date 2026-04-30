"""Runtime session, turn, event, and process lifecycle helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.observability.service import append_platform_log, record_platform_audit, record_platform_event
from core.runtime.errors import RuntimeTransitionError
from core.runtime.routing import build_runtime_routing
from core.runtime.runtime_session import RuntimeSessionGrantRecord, RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
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
    owner_user_id: str | None = None,
    created_by_user_id: str | None = None,
    creator_runtime_session_id: str | None = None,
    grants: list[RuntimeSessionGrantRecord | dict[str, str | None]] | None = None,
    governance: WorkspaceGovernanceRecord | None = None,
    platform_allows_full_access: bool = False,
    now: datetime | None = None,
    start_path: Path | None = None,
    observability_store=None,
) -> RuntimeSessionRecord:
    """Create one runtime session and its initial runtime state."""
    timestamp = now or utcnow()
    routing = build_runtime_routing(
        session_id=session_id,
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
        owner_user_id=owner_user_id.strip() if isinstance(owner_user_id, str) and owner_user_id.strip() else None,
        created_by_user_id=created_by_user_id.strip() if isinstance(created_by_user_id, str) and created_by_user_id.strip() else None,
        creator_runtime_session_id=creator_runtime_session_id.strip() if isinstance(creator_runtime_session_id, str) and creator_runtime_session_id.strip() else None,
        grants=_platform_runtime_grants(grants),
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



def _platform_runtime_grants(
    grants: list[RuntimeSessionGrantRecord | dict[str, str | None]] | None,
) -> list[RuntimeSessionGrantRecord]:
    normalized: list[RuntimeSessionGrantRecord] = []
    for grant in grants or []:
        if isinstance(grant, RuntimeSessionGrantRecord):
            if grant.source == "platform" and grant.grantee_id:
                normalized.append(grant)
            continue
        if not isinstance(grant, dict) or grant.get("source") != "platform":
            continue
        operation = grant.get("operation")
        grantee_kind = grant.get("grantee_kind")
        grantee_id = grant.get("grantee_id")
        if operation not in {"cleanup", "interrupt", "restart"}:
            continue
        if grantee_kind not in {"user", "app", "runtime_session"}:
            continue
        if not isinstance(grantee_id, str) or not grantee_id.strip():
            continue
        issued_by_user_id = grant.get("issued_by_user_id")
        normalized.append(
            RuntimeSessionGrantRecord(
                operation=operation,
                grantee_kind=grantee_kind,
                grantee_id=grantee_id.strip(),
                issued_by_user_id=issued_by_user_id if isinstance(issued_by_user_id, str) else None,
            )
        )
    return normalized



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
    runtime_root = Path(parent.runtime_root).parent / child_session_id
    runtime_root.mkdir(parents=True, exist_ok=True)
    session = RuntimeSessionRecord(
        session_id=child_session_id,
        workspace_id=parent.workspace_id,
        agent_id=child_agent_id,
        status="created",
        requested_mode=parent.requested_mode,
        effective_mode=parent.effective_mode,
        workspace_root=parent.workspace_root,
        workdir=parent.workdir,
        runtime_root=str(runtime_root),
        started_at=None,
        updated_at=timestamp,
        ended_at=None,
        last_progress_at=None,
        system_prompt=parent.system_prompt,
        skill_ids=list(parent.skill_ids),
        source_app_id=parent.source_app_id,
        owner_user_id=parent.owner_user_id,
        created_by_user_id=parent.owner_user_id,
        creator_runtime_session_id=parent.session_id,
        grants=list(parent.grants),
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
