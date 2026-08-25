"""Persisted adaptive scheduler for dynamic inter-agent orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from core.inter_agent.errors import InterAgentOperationError, InterAgentValidationError
from core.inter_agent.orchestration_planner_catalog import OrchestrationPlannerCatalog
from core.inter_agent.orchestration_control import (
    ControlCompletion,
    apply_control_decision,
    apply_pending_control_decisions,
    create_initial_plan,
    next_control_decision,
)
from core.inter_agent.orchestration_runtime import (
    ParticipantTurnExecutor,
    prepare_generalist_handoff,
    runtime_turn_executor,
)
from core.inter_agent.orchestration_participants import AgentSnapshotResolver
from core.inter_agent.orchestration_state import OrchestrationControlState, load_control_state
from core.inter_agent.orchestration_tasks import (
    OrchestrationTaskResult,
    execute_task,
    materialize_plan,
    materialize_tasks,
    record_plan,
)
from core.inter_agent.service import InterAgentService


@dataclass(frozen=True)
class OrchestrationExecutionResult:
    run: Any
    task_results: tuple[OrchestrationTaskResult, ...]
    final_answer: str = ""


def execute_orchestrated_run(
    service: InterAgentService,
    state: Any,
    *,
    workspace_id: str,
    run_id: str,
    turn_executor: ParticipantTurnExecutor | None = None,
    agent_snapshot_resolver: AgentSnapshotResolver | None = None,
    available_agent_type_ids: tuple[str, ...] = (),
    planner_catalog: OrchestrationPlannerCatalog | None = None,
    now: datetime | None = None,
) -> OrchestrationExecutionResult:
    """Resume or execute one adaptive orchestration from its persisted event state."""
    if planner_catalog is None:
        planner_catalog = OrchestrationPlannerCatalog.from_text_entries(available_agent_type_ids)
    run = service.store.get_run(run_id, workspace_id=workspace_id)
    if run.mode != "orchestrated":
        raise InterAgentOperationError("Dynamic scheduler requires an orchestrated run.")
    scheduler_generation = run.recovery_generation
    control: OrchestrationControlState | None = None
    try:
        control = load_control_state(service, run)
        if run.status == "paused":
            return OrchestrationExecutionResult(run=run, task_results=tuple(control.results.values()))
        if run.status in {"failed", "cancelled"} or (
            run.status == "completed" and not control.pending_control_decisions
        ):
            return OrchestrationExecutionResult(run=run, task_results=())
        orchestrator = service.store.get_participant(
            run.orchestrator_participant_id,
            workspace_id=workspace_id,
            run_id=run.run_id,
        )
        execute_turn = turn_executor or runtime_turn_executor(
            service,
            state,
            run,
            expected_recovery_generation=scheduler_generation,
        )
        handoff = prepare_generalist_handoff(
            service,
            state,
            run,
            expected_recovery_generation=scheduler_generation,
        )
        budget = service.store.get_budget_policy(run.budget_policy_id, workspace_id=workspace_id)
        pending_completion = apply_pending_control_decisions(
            service,
            run,
            orchestrator,
            control,
            agent_snapshot_resolver=agent_snapshot_resolver,
            expected_recovery_generation=scheduler_generation,
        )
        if pending_completion is not None:
            return _execution_result(pending_completion)
        if not control.tasks:
            run = _transition_scheduler_run(
                service,
                run,
                expected_recovery_generation=scheduler_generation,
                status="planning",
                now=now or datetime.now(tz=UTC),
            )
            plan = create_initial_plan(
                service,
                run,
                orchestrator,
                control,
                handoff.input_text,
                handoff.analysis_text,
                execute_turn,
                state,
                max_initial_tasks=_initial_task_limit(budget.max_participants),
                available_agent_type_ids=available_agent_type_ids,
                planner_catalog=planner_catalog,
                expected_recovery_generation=scheduler_generation,
            )
            record_plan(
                service,
                run,
                plan,
                expected_recovery_generation=scheduler_generation,
            )
            materialize_plan(
                service,
                run,
                orchestrator,
                plan,
                snapshot_resolver=agent_snapshot_resolver,
                expected_recovery_generation=scheduler_generation,
            )
            control.tasks.update((task.task_id, task) for task in plan.tasks)
        else:
            materialize_tasks(
                service,
                run,
                orchestrator,
                tuple(control.tasks.values()),
                snapshot_resolver=agent_snapshot_resolver,
                expected_recovery_generation=scheduler_generation,
            )
        run = _transition_scheduler_run(
            service,
            run,
            expected_recovery_generation=scheduler_generation,
            status="running",
            now=datetime.now(tz=UTC),
        )
        max_control_steps = max(2, budget.max_total_turns)
        while control.control_step < max_control_steps:
            latest_run = service.store.get_run(run.run_id, workspace_id=workspace_id)
            if (
                latest_run.status in {"paused", "cancelled", "failed"}
                or latest_run.recovery_generation != scheduler_generation
            ):
                raise InterAgentOperationError("Orchestration stopped while scheduling work.")
            ready = control.ready_tasks()
            if ready:
                completion = _execute_ready_wave(
                    service,
                    state,
                    latest_run,
                    orchestrator,
                    control,
                    ready,
                    input_text=handoff.input_text,
                    execute_turn=execute_turn,
                    max_concurrency=budget.max_concurrent_participants,
                    max_participants=budget.max_participants,
                    max_control_steps=max_control_steps,
                    agent_snapshot_resolver=agent_snapshot_resolver,
                    available_agent_type_ids=available_agent_type_ids,
                    planner_catalog=planner_catalog,
                    expected_recovery_generation=scheduler_generation,
                )
                if completion is not None:
                    return _execution_result(completion)
                continue
            before = (len(control.tasks), len(control.results))
            recorded = next_control_decision(
                service,
                latest_run,
                orchestrator,
                control,
                input_text=handoff.input_text,
                trigger_task_id=None,
                execute_turn=execute_turn,
                runtime_state=state,
                max_participants=budget.max_participants,
                available_agent_type_ids=available_agent_type_ids,
                planner_catalog=planner_catalog,
                expected_recovery_generation=scheduler_generation,
            )
            completion = apply_control_decision(
                service,
                latest_run,
                orchestrator,
                control,
                recorded,
                agent_snapshot_resolver=agent_snapshot_resolver,
                expected_recovery_generation=scheduler_generation,
            )
            if completion is not None:
                return _execution_result(completion)
            if before == (len(control.tasks), len(control.results)):
                reason = "No dependency-ready tasks remain." if control.pending_task_ids else "No follow-up work was scheduled."
                raise InterAgentOperationError(f"{reason} The orchestrator did not repair or complete the run.")
        raise InterAgentOperationError("Orchestration exceeded its adaptive control-step budget.")
    except Exception as error:
        latest = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
        if latest.status == "paused" or latest.recovery_generation != scheduler_generation:
            return OrchestrationExecutionResult(
                run=latest,
                task_results=tuple(control.results.values()) if control is not None else (),
            )
        _record_failed_run(
            service,
            run,
            error,
            expected_recovery_generation=scheduler_generation,
        )
        latest = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
        if latest.status == "paused" or latest.recovery_generation != scheduler_generation:
            return OrchestrationExecutionResult(
                run=latest,
                task_results=tuple(control.results.values()) if control is not None else (),
            )
        if isinstance(error, (InterAgentOperationError, InterAgentValidationError)):
            raise
        raise InterAgentOperationError(str(error)) from error


def _execute_ready_wave(
    service: InterAgentService,
    runtime_state: Any,
    run: Any,
    orchestrator: Any,
    control: OrchestrationControlState,
    ready: list[Any],
    *,
    input_text: str,
    execute_turn: ParticipantTurnExecutor,
    max_concurrency: int,
    max_participants: int,
    max_control_steps: int,
    agent_snapshot_resolver: AgentSnapshotResolver | None,
    available_agent_type_ids: tuple[str, ...],
    planner_catalog: OrchestrationPlannerCatalog | None,
    expected_recovery_generation: int,
) -> ControlCompletion | None:
    running_ids = {task.task_id for task in ready}
    with ThreadPoolExecutor(max_workers=max(1, min(max_concurrency, len(ready)))) as pool:
        futures = {
            pool.submit(
                execute_task,
                service,
                run,
                task,
                service.store.get_participant(task.task_id, workspace_id=run.workspace_id, run_id=run.run_id),
                input_text,
                {dependency: control.results[dependency].output_text for dependency in task.depends_on},
                execute_turn,
                expected_recovery_generation=expected_recovery_generation,
            ): task
            for task in ready
        }
        for future in as_completed(futures):
            task = futures[future]
            control.results[task.task_id] = future.result()
            running_ids.discard(task.task_id)
            latest_run = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
            if (
                latest_run.status in {"paused", "cancelled", "failed"}
                or latest_run.recovery_generation != expected_recovery_generation
            ):
                raise InterAgentOperationError("Orchestration stopped while task workers were unwinding.")
            if control.control_step >= max_control_steps:
                raise InterAgentOperationError("Orchestration exceeded its adaptive control-step budget.")
            recorded = next_control_decision(
                service,
                run,
                orchestrator,
                control,
                input_text=input_text,
                trigger_task_id=task.task_id,
                execute_turn=execute_turn,
                runtime_state=runtime_state,
                max_participants=max_participants,
                available_agent_type_ids=available_agent_type_ids,
                planner_catalog=planner_catalog,
                non_cancellable_task_ids=running_ids,
                expected_recovery_generation=expected_recovery_generation,
            )
            completion = apply_control_decision(
                service,
                run,
                orchestrator,
                control,
                recorded,
                agent_snapshot_resolver=agent_snapshot_resolver,
                expected_recovery_generation=expected_recovery_generation,
            )
            if completion is not None:
                if running_ids:
                    raise InterAgentValidationError("Orchestrator cannot complete while worker tasks are still running.")
                return completion
    return None


def _initial_task_limit(max_participants: int) -> int:
    worker_slots = max(1, max_participants - 1)
    return max(1, min(worker_slots, round(worker_slots * 0.7)))


def _execution_result(completion: ControlCompletion) -> OrchestrationExecutionResult:
    return OrchestrationExecutionResult(
        run=completion.run,
        task_results=completion.task_results,
        final_answer=completion.final_answer,
    )


def _record_failed_run(
    service: InterAgentService,
    run: Any,
    error: Exception,
    *,
    expected_recovery_generation: int,
) -> None:
    try:
        with service.store.scheduler_mutation(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            expected_recovery_generation=expected_recovery_generation,
        ) as current_run:
            failed_at = datetime.now(tz=UTC)
            failed = replace(current_run, status="failed", updated_at=failed_at, ended_at=failed_at)
            service.store.save_run(failed)
            service.record_event(
                failed,
                event_type="inter_agent.run.failed",
                participant_id=failed.orchestrator_participant_id,
                visibility_plane="summary",
                correlation_id=failed.run_id,
                idempotency_key=f"{failed.run_id}:dynamic.failed",
                payload={"status": "failed", "error": str(error)},
            )
    except InterAgentOperationError:
        return


def _transition_scheduler_run(
    service: InterAgentService,
    run: Any,
    *,
    expected_recovery_generation: int,
    status: str,
    now: datetime,
) -> Any:
    with service.store.scheduler_mutation(
        workspace_id=run.workspace_id,
        run_id=run.run_id,
        expected_recovery_generation=expected_recovery_generation,
    ) as current_run:
        updated = replace(current_run, status=status, updated_at=now, ended_at=None)
        service.store.save_run(updated)
        return updated
