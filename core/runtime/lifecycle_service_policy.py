"""Reconcile persisted sessions with current execution policy."""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from core.runtime.lifecycle_service_sessions import utcnow
from core.runtime.routing import build_runtime_routing
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeStore
from core.workspaces.models import WorkspaceGovernanceRecord

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
    return store.patch_session_metadata(
        session_id=session.session_id,
        workspace_id=session.workspace_id,
        updates={
            "effective_mode": routing.effective_mode,
            "workspace_root": routing.workspace_root,
            "workdir": routing.workdir,
            "runtime_root": routing.runtime_root,
        },
        now=timestamp,
    )
