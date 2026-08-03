"""Replayable scheduler state for orchestrated inter-agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.inter_agent.orchestration_plan import (
    OrchestrationControlDecision,
    OrchestrationTaskSpec,
    control_decision_from_payload,
    parse_review_decision,
    task_spec_from_payload,
)
from core.inter_agent.orchestration_topology import reserved_task_ids_for_run
from core.inter_agent.orchestration_tasks import OrchestrationTaskResult
from core.inter_agent.service import InterAgentService


@dataclass(frozen=True)
class RecordedControlDecision:
    event_id: str
    control_step: int
    decision: OrchestrationControlDecision


@dataclass(frozen=True)
class QualityGateStatus:
    passed: bool
    frontier_task_ids: tuple[str, ...]
    reviewed_frontier_task_ids: tuple[str, ...] = ()
    review_task_id: str | None = None
    blocking_review_task_ids: tuple[str, ...] = ()


@dataclass
class OrchestrationControlState:
    tasks: dict[str, OrchestrationTaskSpec] = field(default_factory=dict)
    results: dict[str, OrchestrationTaskResult] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    recorded_control_decisions: dict[int, RecordedControlDecision] = field(default_factory=dict)
    applied_control_steps: set[int] = field(default_factory=set)
    control_step: int = 0
    plan_summary: str = ""
    latest_decision_summary: str = ""

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

    @property
    def pending_control_decisions(self) -> tuple[RecordedControlDecision, ...]:
        return tuple(
            decision
            for step, decision in sorted(self.recorded_control_decisions.items())
            if step not in self.applied_control_steps
        )

    def quality_gate_status(self) -> QualityGateStatus:
        completed = self.completed_task_ids
        material = {
            task_id
            for task_id, task in self.tasks.items()
            if task_id in completed and task.role not in {"reviewer", "security_reviewer"}
        }
        if not material:
            return QualityGateStatus(passed=False, frontier_task_ids=())
        ancestors = {task_id: self._completed_ancestors(task_id) for task_id in completed}
        frontier = tuple(
            task_id
            for task_id in self.tasks
            if task_id in material
            and not any(task_id in ancestors.get(other_id, set()) for other_id in material if other_id != task_id)
        )
        rejected_reviews = self.blocking_review_task_ids()
        for task_id in self.approved_review_task_ids():
            reviewed = tuple(item for item in frontier if item in ancestors.get(task_id, set()))
            unresolved_rejections = tuple(
                review_id for review_id in rejected_reviews if review_id not in ancestors.get(task_id, set())
            )
            if reviewed == frontier and not unresolved_rejections:
                return QualityGateStatus(
                    passed=True,
                    frontier_task_ids=frontier,
                    reviewed_frontier_task_ids=reviewed,
                    review_task_id=task_id,
                )
        return QualityGateStatus(
            passed=False,
            frontier_task_ids=frontier,
            blocking_review_task_ids=rejected_reviews,
        )

    def approved_review_task_ids(self) -> tuple[str, ...]:
        return self._review_task_ids(approved=True)

    def rejected_review_task_ids(self) -> tuple[str, ...]:
        return self._review_task_ids(approved=False)

    def blocking_review_task_ids(self) -> tuple[str, ...]:
        return self._review_task_ids(approved=False, invalid_is_match=True)

    def _review_task_ids(self, *, approved: bool, invalid_is_match: bool = False) -> tuple[str, ...]:
        matching: list[str] = []
        for task_id, task in self.tasks.items():
            result = self.results.get(task_id)
            if task.role not in {"reviewer", "security_reviewer"} or not task.review_of or result is None:
                continue
            if result.status != "completed" or task.review_of not in self.completed_task_ids:
                continue
            try:
                if parse_review_decision(result.output_text).approved is approved:
                    matching.append(task_id)
            except Exception:
                if invalid_is_match:
                    matching.append(task_id)
        return tuple(matching)

    def has_approved_review(self) -> bool:
        return self.quality_gate_status().passed

    def _completed_ancestors(self, task_id: str) -> set[str]:
        completed = self.completed_task_ids
        ancestors: set[str] = set()
        source_task = self.tasks.get(task_id)
        pending = list(source_task.depends_on) if source_task is not None else []
        while pending:
            dependency = pending.pop()
            if dependency in ancestors or dependency not in completed:
                continue
            ancestors.add(dependency)
            task = self.tasks.get(dependency)
            if task is not None:
                pending.extend(task.depends_on)
        return ancestors


def load_control_state(service: InterAgentService, run: Any) -> OrchestrationControlState:
    state = OrchestrationControlState()
    reserved_task_ids = reserved_task_ids_for_run(run.orchestrator_participant_id)
    events = service.store.list_event_page(
        run.run_id,
        workspace_id=run.workspace_id,
        visibility_plane="debug",
        limit=500,
    ).events
    for event in events:
        if event.event_type == "inter_agent.plan.summary_created":
            state.plan_summary = str(event.payload.get("summary") or state.plan_summary)
            _add_task_payloads(state, event.payload.get("tasks"), reserved_task_ids=reserved_task_ids)
        elif event.event_type == "inter_agent.control.decision":
            control_step = int(event.payload.get("control_step") or 0)
            decision = control_decision_from_payload(
                event.payload,
                existing_tasks=tuple(state.tasks.values()),
                reserved_task_ids=reserved_task_ids,
            )
            state.control_step = max(state.control_step, control_step)
            state.recorded_control_decisions[control_step] = RecordedControlDecision(
                event_id=event.event_id,
                control_step=control_step,
                decision=decision,
            )
            state.latest_decision_summary = decision.summary
            _add_task_payloads(state, event.payload.get("tasks"), reserved_task_ids=reserved_task_ids)
        elif event.event_type == "inter_agent.control.decision_applied":
            state.applied_control_steps.add(int(event.payload.get("control_step") or 0))
        elif event.event_type == "inter_agent.task.created":
            task_payload = event.payload.get("task")
            if isinstance(task_payload, dict):
                _add_task_payloads(state, [task_payload], reserved_task_ids=reserved_task_ids)
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


def _add_task_payloads(
    state: OrchestrationControlState,
    value: Any,
    *,
    reserved_task_ids: set[str] | frozenset[str],
) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        task = task_spec_from_payload(item, reserved_task_ids=reserved_task_ids)
        state.tasks.setdefault(task.task_id, task)
