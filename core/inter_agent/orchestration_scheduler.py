"""Core-owned coordinator for dynamic, dependency-aware orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from core.inter_agent.errors import InterAgentOperationError, InterAgentValidationError
from core.inter_agent.orchestration_plan import parse_completion_decision, parse_orchestration_plan
from core.inter_agent.orchestration_prompts import completion_prompt, planning_prompt
from core.inter_agent.orchestration_review import run_review_revisions
from core.inter_agent.orchestration_runtime import (
    ParticipantTurnExecutor,
    runtime_turn_executor,
    sync_generalist_directives,
)
from core.inter_agent.orchestration_tasks import (
    OrchestrationTaskResult,
    execute_dependency_graph,
    materialize_plan,
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
    input_text: str,
    turn_executor: ParticipantTurnExecutor | None = None,
    now: datetime | None = None,
) -> OrchestrationExecutionResult:
    """Plan, materialize, schedule, review, and complete one dynamic run."""
    run = service.store.get_run(run_id, workspace_id=workspace_id)
    if run.mode != "orchestrated":
        raise InterAgentOperationError("Dynamic scheduler requires an orchestrated run.")
    if run.status in {"completed", "failed", "cancelled"}:
        return OrchestrationExecutionResult(run=run, task_results=())
    timestamp = now or datetime.now(tz=UTC)
    run = replace(run, status="planning", updated_at=timestamp)
    service.store.save_run(run)
    orchestrator = service.store.get_participant(
        run.orchestrator_participant_id,
        workspace_id=workspace_id,
        run_id=run.run_id,
    )
    execute_turn = turn_executor or runtime_turn_executor(service, state, run)
    try:
        sync_generalist_directives(service, state, run)
        planning_directives = service.pending_directives(run)
        plan_output = execute_turn(
            orchestrator,
            planning_prompt(input_text, run.orchestration_policy, planning_directives),
            f"{run.run_id}:orchestrator:plan",
        )
        service.mark_directives_delivered(run, planning_directives)
        budget = service.store.get_budget_policy(run.budget_policy_id, workspace_id=workspace_id)
        revision_slots = 2 * max(0, budget.max_rounds - 1)
        max_initial_tasks = budget.max_participants - 1 - revision_slots
        if max_initial_tasks < 2:
            raise InterAgentValidationError("Orchestration budget cannot reserve an implementer/reviewer revision loop.")
        plan = parse_orchestration_plan(plan_output, max_tasks=max_initial_tasks)
        record_plan(service, run, plan)
        task_participants = materialize_plan(service, run, orchestrator, plan)
        run = replace(run, status="running", updated_at=datetime.now(tz=UTC))
        service.store.save_run(run)
        results = execute_dependency_graph(
            service,
            run,
            plan,
            task_participants,
            input_text=input_text,
            execute_turn=execute_turn,
            max_concurrency=budget.max_concurrent_participants,
        )
        results = run_review_revisions(
            service,
            run,
            plan,
            orchestrator,
            results,
            input_text=input_text,
            execute_turn=execute_turn,
            max_rounds=budget.max_rounds,
        )
        sync_generalist_directives(service, state, run)
        completion_directives = service.pending_directives(run)
        completion_output = execute_turn(
            orchestrator,
            completion_prompt(input_text, results, completion_directives),
            f"{run.run_id}:orchestrator:completion",
        )
        service.mark_directives_delivered(run, completion_directives)
        decision = parse_completion_decision(completion_output)
        completed = service.decide_completion(
            workspace_id=workspace_id,
            run_id=run.run_id,
            participant_id=orchestrator.participant_id,
            complete=decision.complete,
            quality_passed=decision.quality_passed,
            summary=decision.summary,
            final_answer=decision.final_answer,
        )
        if not decision.complete:
            raise InterAgentOperationError("Orchestrator requested revision after the configured review rounds.")
        service.release_budget(completed, reservation_id=f"spawn:{orchestrator.participant_id}")
        return OrchestrationExecutionResult(
            run=completed,
            task_results=tuple(results.values()),
            final_answer=decision.final_answer,
        )
    except Exception as error:
        _record_failed_run(service, run, error)
        if isinstance(error, (InterAgentOperationError, InterAgentValidationError)):
            raise
        raise InterAgentOperationError(str(error)) from error


def _record_failed_run(service: InterAgentService, run: Any, error: Exception) -> None:
    latest = service.store.get_run(run.run_id, workspace_id=run.workspace_id)
    if latest.status in {"completed", "cancelled", "failed"}:
        return
    failed_at = datetime.now(tz=UTC)
    latest = replace(latest, status="failed", updated_at=failed_at, ended_at=failed_at)
    service.store.save_run(latest)
    service.record_event(
        latest,
        event_type="inter_agent.run.failed",
        participant_id=latest.orchestrator_participant_id,
        visibility_plane="summary",
        correlation_id=latest.run_id,
        idempotency_key=f"{latest.run_id}:dynamic.failed",
        payload={"status": "failed", "error": str(error)},
    )
