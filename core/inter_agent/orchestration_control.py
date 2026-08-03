"""Validated orchestrator decisions and their persisted state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_decisions import record_control_decision, record_control_decision_applied
from core.inter_agent.orchestration_plan import (
    OrchestrationControlDecision,
    OrchestrationPlan,
    parse_control_decision,
    parse_orchestration_plan,
)
from core.inter_agent.orchestration_prompts import control_prompt, planning_prompt
from core.inter_agent.orchestration_participants import AgentSnapshotResolver
from core.inter_agent.orchestration_runtime import ParticipantTurnExecutor, sync_generalist_directives
from core.inter_agent.orchestration_state import OrchestrationControlState, RecordedControlDecision
from core.inter_agent.orchestration_topology import reserved_task_ids_for_run
from core.inter_agent.orchestration_tasks import (
    OrchestrationTaskResult,
    cancel_task,
    materialize_tasks,
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
    plan = parse_orchestration_plan(
        output,
        max_tasks=max_initial_tasks,
        require_review_gate=False,
        reserved_task_ids=reserved_task_ids_for_run(run.orchestrator_participant_id),
    )
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
    non_cancellable_task_ids: set[str] | None = None,
) -> RecordedControlDecision:
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
        reserved_task_ids=reserved_task_ids_for_run(run.orchestrator_participant_id),
    )
    _validate_control_decision(
        control,
        decision,
        non_cancellable_task_ids=non_cancellable_task_ids or set(),
    )
    event = record_control_decision(service, run, decision, control_step=step, trigger_task_id=trigger_task_id)
    service.mark_directives_delivered(run, directives)
    control.control_step = step
    recorded = RecordedControlDecision(event_id=event.event_id, control_step=step, decision=decision)
    control.recorded_control_decisions[step] = recorded
    return recorded


def apply_control_decision(
    service: InterAgentService,
    run: Any,
    orchestrator: Any,
    control: OrchestrationControlState,
    recorded: RecordedControlDecision,
    *,
    agent_snapshot_resolver: AgentSnapshotResolver | None,
) -> ControlCompletion | None:
    decision = recorded.decision
    _validate_control_decision(control, decision)
    for task_id in decision.cancel_task_ids:
        result = control.results.get(task_id)
        if result is not None and result.status == "cancelled":
            continue
        task = control.tasks[task_id]
        participant = service.store.get_participant(task_id, workspace_id=run.workspace_id, run_id=run.run_id)
        control.results[task_id] = cancel_task(service, run, task, participant)
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
        _record_decision_applied(service, run, control, recorded)
        return None
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
    _record_decision_applied(service, completed, control, recorded)
    return ControlCompletion(
        run=completed,
        task_results=tuple(control.results.values()),
        final_answer=decision.final_answer,
    )


def apply_pending_control_decisions(
    service: InterAgentService,
    run: Any,
    orchestrator: Any,
    control: OrchestrationControlState,
    *,
    agent_snapshot_resolver: AgentSnapshotResolver | None,
) -> ControlCompletion | None:
    """Apply every recorded decision missing its durable application marker."""
    for recorded in control.pending_control_decisions:
        completion = apply_control_decision(
            service,
            run,
            orchestrator,
            control,
            recorded,
            agent_snapshot_resolver=agent_snapshot_resolver,
        )
        if completion is not None:
            return completion
    return None


def _validate_control_decision(
    control: OrchestrationControlState,
    decision: OrchestrationControlDecision,
    *,
    non_cancellable_task_ids: set[str] | None = None,
) -> None:
    cancelled = set(decision.cancel_task_ids)
    running = non_cancellable_task_ids or set()
    if cancelled.intersection(running):
        raise InterAgentValidationError("Orchestrator cannot cancel tasks already running in the current wave.")
    for task_id in cancelled:
        result = control.results.get(task_id)
        if result is not None and result.status != "cancelled":
            raise InterAgentValidationError(f"Orchestrator cannot cancel terminal task `{task_id}`.")
    if any(set(task.depends_on).intersection(cancelled) for task in decision.tasks):
        raise InterAgentValidationError("New orchestration tasks cannot depend on work cancelled in the same decision.")
    if not decision.complete:
        return
    known_task_ids = set(control.tasks).union(task.task_id for task in decision.tasks)
    pending_after_application = known_task_ids - set(control.results) - cancelled
    if pending_after_application:
        raise InterAgentValidationError("Orchestrator cannot complete while scheduled tasks remain pending.")
    if not control.has_approved_review():
        raise InterAgentValidationError(
            "Orchestrator completion requires an approved final review covering the latest material task frontier "
            "and resolving every rejected, malformed, or failed review."
        )


def _record_decision_applied(
    service: InterAgentService,
    run: Any,
    control: OrchestrationControlState,
    recorded: RecordedControlDecision,
) -> None:
    record_control_decision_applied(
        service,
        run,
        control_step=recorded.control_step,
        decision_event_id=recorded.event_id,
    )
    control.applied_control_steps.add(recorded.control_step)
