"""Persistence markers for replayable orchestrator control decisions."""

from __future__ import annotations

from typing import Any

from core.inter_agent.events import InterAgentEventRecord
from core.inter_agent.orchestration_plan import OrchestrationControlDecision, task_payload
from core.inter_agent.service import InterAgentService


def record_control_decision(
    service: InterAgentService,
    run: Any,
    decision: OrchestrationControlDecision,
    *,
    control_step: int,
    trigger_task_id: str | None,
) -> InterAgentEventRecord:
    return service.record_event(
        run,
        event_type="inter_agent.control.decision",
        participant_id=run.orchestrator_participant_id,
        visibility_plane="detail",
        correlation_id=f"{run.run_id}:control:{control_step}",
        idempotency_key=f"{run.run_id}:dynamic.control:{control_step}",
        payload={
            "control_step": control_step,
            "application_status": "recorded",
            "trigger_task_id": trigger_task_id,
            "summary": decision.summary,
            "tasks": [task_payload(task) for task in decision.tasks],
            "cancel_task_ids": list(decision.cancel_task_ids),
            "complete": decision.complete,
            "quality_passed": decision.quality_passed,
            "final_answer": decision.final_answer if decision.complete else "",
        },
    )


def record_control_decision_applied(
    service: InterAgentService,
    run: Any,
    *,
    control_step: int,
    decision_event_id: str,
) -> InterAgentEventRecord:
    return service.record_event(
        run,
        event_type="inter_agent.control.decision_applied",
        participant_id=run.orchestrator_participant_id,
        visibility_plane="detail",
        correlation_id=f"{run.run_id}:control:{control_step}",
        idempotency_key=f"{run.run_id}:dynamic.control.applied:{control_step}",
        payload={
            "control_step": control_step,
            "decision_event_id": decision_event_id,
            "application_status": "applied",
        },
    )
