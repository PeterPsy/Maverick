"""Validated orchestrator decisions and their persisted state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_plan import (
    OrchestrationControlDecision,
    OrchestrationPlan,
    parse_control_decision,
    parse_orchestration_plan,
)
from core.inter_agent.orchestration_prompts import control_prompt, planning_prompt
from core.inter_agent.orchestration_runtime import ParticipantTurnExecutor, sync_generalist_directives
from core.inter_agent.orchestration_state import OrchestrationControlState
from core.inter_agent.orchestration_tasks import (
    AgentSnapshotResolver,
    OrchestrationTaskResult,
    cancel_task,
    materialize_tasks,
    record_control_decision,
)
from core.inter_agent.service import InterAgentService


@dataclass(frozen=True)
class ControlCompletion:
    run: Any
    task_results: tuple[OrchestrationTaskResult, ...]
    final_answer: str


def create_initial_plan(
    service: InterAgentService,
    run: Any,
    orchestrator: Any,
    control: OrchestrationControlState,
    input_text: str,
    generalist_analysis: str,
    execute_turn: ParticipantTurnExecutor,
    runtime_state: Any,
    *,
    max_initial_tasks: int,
    available_agent_type_ids: tuple[str, ...],
) -> OrchestrationPlan:
    sync_generalist_directives(service, runtime_state, run)
    directives = service.pending_directives(run)
    output = execute_turn(
        orchestrator,
        planning_prompt(
            input_text,
            generalist_analysis,
            run.orchestration_policy,
            directives,
            list(available_agent_type_ids),
        ),
        f"{run.run_id}:orchestrator:plan",
    )
    plan = parse_orchestration_plan(output, max_tasks=max_initial_tasks, require_review_gate=False)
    service.mark_directives_delivered(run, directives)
    control.plan_summary = plan.summary
    return plan


def next_control_decision(
    service: InterAgentService,
    run: Any,
    orchestrator: Any,
    control: OrchestrationControlState,
    *,
    input_text: str,
    trigger_task_id: str | None,
    execute_turn: ParticipantTurnExecutor,
    runtime_state: Any,
    max_participants: int,
    available_agent_type_ids: tuple[str, ...],
) -> OrchestrationControlDecision:
    sync_generalist_directives(service, runtime_state, run)
    directives = service.pending_directives(run)
    step = control.control_step + 1
    output = execute_turn(
        orchestrator,
        control_prompt(
            input_text,
            tuple(control.tasks.values()),
            control.results,
            trigger_task_id=trigger_task_id,
            directives=directives,
            available_agent_types=list(available_agent_type_ids),
        ),
        f"{run.run_id}:orchestrator:control:{step}",
    )
    remaining_slots = max(0, max_participants - 1 - len(control.tasks))
    decision = parse_control_decision(
        output,
        existing_tasks=tuple(control.tasks.values()),
        max_new_tasks=remaining_slots,
    )
    record_control_decision(service, run, decision, control_step=step, trigger_task_id=trigger_task_id)
    service.mark_directives_delivered(run, directives)
    control.control_step = step
    return decision


def apply_control_decision(
    service: InterAgentService,
    run: Any,
    orchestrator: Any,
    control: OrchestrationControlState,
    decision: OrchestrationControlDecision,
    *,
    agent_snapshot_resolver: AgentSnapshotResolver | None,
) -> ControlCompletion | None:
    for task_id in decision.cancel_task_ids:
        if task_id in control.results:
            raise InterAgentValidationError(f"Orchestrator cannot cancel terminal task `{task_id}`.")
        task = control.tasks[task_id]
        participant = service.store.get_participant(task_id, workspace_id=run.workspace_id, run_id=run.run_id)
        control.results[task_id] = cancel_task(service, run, task, participant)
    cancelled = set(decision.cancel_task_ids)
    if any(set(task.depends_on).intersection(cancelled) for task in decision.tasks):
        raise InterAgentValidationError("New orchestration tasks cannot depend on work cancelled in the same decision.")
    if decision.tasks:
        materialize_tasks(
            service,
            run,
            orchestrator,
            decision.tasks,
            snapshot_resolver=agent_snapshot_resolver,
        )
        control.tasks.update((task.task_id, task) for task in decision.tasks)
    if not decision.complete:
        return None
    if control.pending_task_ids:
        raise InterAgentValidationError("Orchestrator cannot complete while scheduled tasks remain pending.")
    if not control.has_approved_review():
        raise InterAgentValidationError("Orchestrator completion requires an approved dependent reviewer output.")
    completed = service.decide_completion(
        workspace_id=run.workspace_id,
        run_id=run.run_id,
        participant_id=orchestrator.participant_id,
        complete=True,
        quality_passed=decision.quality_passed,
        summary=decision.summary,
        final_answer=decision.final_answer,
    )
    service.release_budget(completed, reservation_id=f"spawn:{orchestrator.participant_id}")
    return ControlCompletion(
        run=completed,
        task_results=tuple(control.results.values()),
        final_answer=decision.final_answer,
    )
