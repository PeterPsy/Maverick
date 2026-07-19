"""Bounded implementer/reviewer revision loop for orchestrated runs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.models import EdgeSpec, InterAgentParticipantRecord
from core.inter_agent.orchestration_plan import OrchestrationPlan, parse_review_decision
from core.inter_agent.orchestration_runtime import ParticipantTurnExecutor
from core.inter_agent.orchestration_tasks import OrchestrationTaskResult, execute_task, worker_spec
from core.inter_agent.service import InterAgentService


def run_review_revisions(
    service: InterAgentService,
    run: Any,
    plan: OrchestrationPlan,
    orchestrator: InterAgentParticipantRecord,
    results: dict[str, OrchestrationTaskResult],
    *,
    input_text: str,
    execute_turn: ParticipantTurnExecutor,
    max_rounds: int,
) -> dict[str, OrchestrationTaskResult]:
    review_tasks = [task for task in plan.tasks if task.review_of]
    for review_task in review_tasks:
        decision = parse_review_decision(results[review_task.task_id].output_text)
        round_index = 1
        previous_implementer_id = review_task.review_of or ""
        previous_reviewer_id = review_task.task_id
        while not decision.approved and round_index < max_rounds:
            round_index += 1
            implementation_task = next(task for task in plan.tasks if task.task_id == review_task.review_of)
            revision_id = f"{implementation_task.task_id}-r{round_index}"
            revision_review_id = f"{review_task.task_id}-r{round_index}"
            revision_task = replace(
                implementation_task,
                task_id=revision_id,
                objective=f"{implementation_task.objective}\n\nReviewer feedback:\n{decision.feedback}",
                depends_on=(previous_reviewer_id,),
            )
            revision_reviewer = replace(
                review_task,
                task_id=revision_review_id,
                depends_on=(revision_id,),
                review_of=revision_id,
            )
            implementation_participant = service.add_participant(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                spec=worker_spec(orchestrator, revision_task, participant_id=revision_id),
            )
            reviewer_participant = service.add_participant(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                spec=worker_spec(orchestrator, revision_reviewer, participant_id=revision_review_id),
            )
            service.add_edge(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                spec=EdgeSpec(source_id=previous_reviewer_id, target_id=revision_id, kind="handed_off", label="Revision"),
            )
            service.add_edge(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                spec=EdgeSpec(source_id=revision_id, target_id=revision_review_id, kind="reviewed_by", label="Quality review"),
            )
            implementation_result = execute_task(
                service,
                run,
                revision_task,
                implementation_participant,
                input_text,
                {
                    previous_implementer_id: results[previous_implementer_id].output_text,
                    previous_reviewer_id: results[previous_reviewer_id].output_text,
                },
                execute_turn,
            )
            reviewer_result = execute_task(
                service,
                run,
                revision_reviewer,
                reviewer_participant,
                input_text,
                {revision_id: implementation_result.output_text},
                execute_turn,
            )
            results[revision_id] = implementation_result
            results[revision_review_id] = reviewer_result
            decision = parse_review_decision(reviewer_result.output_text)
            previous_implementer_id = revision_id
            previous_reviewer_id = revision_review_id
        if not decision.approved:
            raise InterAgentOperationError("Reviewer did not approve the implementation within the revision budget.")
    return results
