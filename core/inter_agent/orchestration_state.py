"""Replayable scheduler state for orchestrated inter-agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.inter_agent.orchestration_plan import (
    OrchestrationTaskSpec,
    parse_review_decision,
    task_spec_from_payload,
)
from core.inter_agent.orchestration_tasks import OrchestrationTaskResult
from core.inter_agent.service import InterAgentService


@dataclass
class OrchestrationControlState:
    tasks: dict[str, OrchestrationTaskSpec] = field(default_factory=dict)
    results: dict[str, OrchestrationTaskResult] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    control_step: int = 0
    plan_summary: str = ""

    @property
    def pending_task_ids(self) -> set[str]:
        return set(self.tasks) - set(self.results)

    @property
    def completed_task_ids(self) -> set[str]:
        return {task_id for task_id, result in self.results.items() if result.status == "completed"}

    def ready_tasks(self) -> list[OrchestrationTaskSpec]:
        completed = self.completed_task_ids
        return [
            task
            for task_id, task in self.tasks.items()
            if task_id in self.pending_task_ids and set(task.depends_on) <= completed
        ]

    def has_approved_review(self) -> bool:
        for task_id, task in self.tasks.items():
            result = self.results.get(task_id)
            if task.role not in {"reviewer", "security_reviewer"} or not task.review_of or result is None:
                continue
            if result.status != "completed" or task.review_of not in self.completed_task_ids:
                continue
            try:
                if parse_review_decision(result.output_text).approved:
                    return True
            except Exception:
                continue
        return False


def load_control_state(service: InterAgentService, run: Any) -> OrchestrationControlState:
    state = OrchestrationControlState()
    events = service.store.list_event_page(
        run.run_id,
        workspace_id=run.workspace_id,
        visibility_plane="debug",
        limit=500,
    ).events
    for event in events:
        if event.event_type == "inter_agent.plan.summary_created":
            state.plan_summary = str(event.payload.get("summary") or state.plan_summary)
            _add_task_payloads(state, event.payload.get("tasks"))
        elif event.event_type == "inter_agent.control.decision":
            state.control_step = max(state.control_step, int(event.payload.get("control_step") or 0))
            _add_task_payloads(state, event.payload.get("tasks"))
        elif event.event_type == "inter_agent.task.created":
            task_payload = event.payload.get("task")
            if isinstance(task_payload, dict):
                _add_task_payloads(state, [task_payload])
            task_id = str(event.payload.get("task_id") or event.correlation_id or "").strip()
            if task_id:
                state.attempts[task_id] = max(state.attempts.get(task_id, 0), int(event.payload.get("attempt") or 1))
        elif event.event_type == "inter_agent.task.retry_scheduled":
            task_id = str(event.payload.get("task_id") or event.correlation_id or "").strip()
            if task_id:
                state.attempts[task_id] = max(state.attempts.get(task_id, 0), int(event.payload.get("attempt") or 1))
        elif event.event_type == "inter_agent.task.completed":
            task_id = str(event.payload.get("task_id") or event.correlation_id or "").strip()
            if not task_id:
                continue
            state.results[task_id] = OrchestrationTaskResult(
                task_id=task_id,
                participant_id=str(event.payload.get("participant_id") or event.participant_id or ""),
                status=str(event.payload.get("status") or "failed"),
                output_text=str(event.payload.get("output_text") or ""),
                error=str(event.payload.get("error") or "").strip() or None,
            )
    return state


def _add_task_payloads(state: OrchestrationControlState, value: Any) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        task = task_spec_from_payload(item)
        state.tasks.setdefault(task.task_id, task)
