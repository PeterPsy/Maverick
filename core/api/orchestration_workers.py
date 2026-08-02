"""Hosted worker lifecycle for persisted orchestrated inter-agent runs."""

from __future__ import annotations

import logging
from threading import Lock, Thread
from typing import Any, Callable

from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.service import InterAgentService
from core.api.orchestration_agent_catalog import build_orchestration_agent_catalog


logger = logging.getLogger(__name__)
_ACTIVE_WORKERS: set[tuple[str, str]] = set()
_ACTIVE_WORKERS_LOCK = Lock()


def start_orchestrated_execution_worker(
    state: Any,
    service: InterAgentService | None = None,
    *,
    workspace_id: str,
    run_id: str,
) -> bool:
    """Start at most one in-process scheduler worker for a persisted run."""
    key = (workspace_id, run_id)
    with _ACTIVE_WORKERS_LOCK:
        if key in _ACTIVE_WORKERS:
            return False
        _ACTIVE_WORKERS.add(key)
    run_service = service or InterAgentService(state.inter_agent_store)

    def worker() -> None:
        try:
            run = run_service.store.get_run(run_id, workspace_id=workspace_id)
            orchestrator = run_service.store.get_participant(
                run.orchestrator_participant_id,
                workspace_id=workspace_id,
                run_id=run.run_id,
            )
            root_session = state.runtime_store.get_session(run.root_runtime_session_id)
            catalog = build_orchestration_agent_catalog(
                state,
                workspace_id=workspace_id,
                created_by_user_id=run.created_by_user_id,
                root_session=root_session,
                orchestrator=orchestrator,
                start_path=state.repository_root,
            )
            execute_orchestrated_run(
                run_service,
                state,
                workspace_id=workspace_id,
                run_id=run_id,
                agent_snapshot_resolver=catalog.resolve,
                available_agent_type_ids=catalog.prompt_entries,
            )
        except Exception:
            logger.exception("Orchestrated inter-agent worker failed for %s/%s.", workspace_id, run_id)
        finally:
            with _ACTIVE_WORKERS_LOCK:
                _ACTIVE_WORKERS.discard(key)

    Thread(target=worker, name=f"maverick-orchestration-{run_id}", daemon=True).start()
    return True


def resume_recovering_orchestrations(
    state: Any,
    *,
    start_worker: Callable[..., bool] = start_orchestrated_execution_worker,
) -> tuple[str, ...]:
    """Enqueue every hosted orchestrated run marked runnable by restart recovery."""
    resumed: list[str] = []
    for workspace in state.workspace_store.list_workspaces():
        for run in state.inter_agent_store.list_runs(workspace.workspace_id):
            if run.mode != "orchestrated" or run.status != "recovering":
                continue
            if start_worker(state, workspace_id=workspace.workspace_id, run_id=run.run_id):
                resumed.append(run.run_id)
    return tuple(resumed)
