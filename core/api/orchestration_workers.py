"""Hosted worker lifecycle for persisted orchestrated inter-agent runs."""

from __future__ import annotations

import logging
from threading import Lock, Thread, current_thread
from typing import Any, Callable

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.service import InterAgentService
from core.api.orchestration_agent_catalog import build_orchestration_agent_catalog


logger = logging.getLogger(__name__)
_ACTIVE_WORKERS: dict[tuple[str, str], Thread] = {}
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
                if _ACTIVE_WORKERS.get(key) is current_thread():
                    _ACTIVE_WORKERS.pop(key, None)

    thread = Thread(target=worker, name=f"maverick-orchestration-{run_id}", daemon=True)
    with _ACTIVE_WORKERS_LOCK:
        if key in _ACTIVE_WORKERS:
            return False
        _ACTIVE_WORKERS[key] = thread
        try:
            thread.start()
        except Exception:
            _ACTIVE_WORKERS.pop(key, None)
            raise
    return True


def wait_for_orchestrated_execution_worker(
    *,
    workspace_id: str,
    run_id: str,
    timeout_seconds: float = 10.0,
) -> bool:
    """Wait for the previous in-process scheduler owner to finish its paused unwind."""
    key = (workspace_id, run_id)
    with _ACTIVE_WORKERS_LOCK:
        thread = _ACTIVE_WORKERS.get(key)
    if thread is None:
        return True
    if thread is current_thread():
        return False
    thread.join(timeout=max(0.0, timeout_seconds))
    return not thread.is_alive()


def resume_orchestrated_execution_worker(
    state: Any,
    service: InterAgentService,
    *,
    workspace_id: str,
    run_id: str,
    reason: str,
    wait_worker: Callable[..., bool] | None = None,
    start_worker: Callable[..., bool] | None = None,
) -> Any:
    """Hand one paused run from its old scheduler owner to a replacement worker."""
    wait_for_worker = wait_worker or wait_for_orchestrated_execution_worker
    start_new_worker = start_worker or start_orchestrated_execution_worker
    if not wait_for_worker(workspace_id=workspace_id, run_id=run_id):
        raise InterAgentOperationError("The previous orchestration scheduler is still stopping.")
    resumed = service.resume_run(
        workspace_id=workspace_id,
        run_id=run_id,
        reason=reason,
    )
    start_new_worker(
        state,
        service,
        workspace_id=workspace_id,
        run_id=run_id,
    )
    return resumed


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
