"""Validated structured decisions produced by a runtime orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_topology import validate_task_ids_not_reserved


_TASK_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_AGENT_TYPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ALLOWED_ROLES = {
    "analyst",
    "implementer",
    "planner",
    "researcher",
    "reviewer",
    "security_reviewer",
    "synthesizer",
    "tester",
}
_REVIEWER_ROLES = {"reviewer", "security_reviewer"}


@dataclass(frozen=True)
class OrchestrationTaskSpec:
    task_id: str
    label: str
    role: str
    objective: str
    depends_on: tuple[str, ...] = ()
    review_of: str | None = None
    agent_type_id: str | None = None

    def __post_init__(self) -> None:
        if self.role in _REVIEWER_ROLES and not self.review_of:
            raise InterAgentValidationError("Reviewer tasks require review_of.")
        if self.review_of and self.role not in _REVIEWER_ROLES:
            raise InterAgentValidationError("Only reviewer tasks may declare review_of.")
        if self.review_of and self.review_of not in self.depends_on:
            raise InterAgentValidationError("Reviewer tasks must depend on their review target.")


@dataclass(frozen=True)
class OrchestrationPlan:
    summary: str
    tasks: tuple[OrchestrationTaskSpec, ...]


@dataclass(frozen=True)
class ReviewDecision:
    approved: bool
    feedback: str


@dataclass(frozen=True)
class CompletionDecision:
    complete: bool
    quality_passed: bool
    summary: str
    final_answer: str


@dataclass(frozen=True)
class OrchestrationControlDecision:
    summary: str
    tasks: tuple[OrchestrationTaskSpec, ...]
    cancel_task_ids: tuple[str, ...]
    complete: bool
    quality_passed: bool
    final_answer: str


def parse_orchestration_plan(
    value: str,
    *,
    max_tasks: int,
    require_review_gate: bool = True,
    reserved_task_ids: set[str] | frozenset[str] = frozenset(),
) -> OrchestrationPlan:
    payload = _json_object(value, decision="plan")
    return orchestration_plan_from_payload(
        payload,
        max_tasks=max_tasks,
        require_review_gate=require_review_gate,
        reserved_task_ids=reserved_task_ids,
    )


def orchestration_plan_from_payload(
    payload: Any,
    *,
    max_tasks: int | None = None,
    require_review_gate: bool = True,
    reserved_task_ids: set[str] | frozenset[str] = frozenset(),
) -> OrchestrationPlan:
    """Rehydrate and atomically validate one persisted orchestrator plan."""
    if not isinstance(payload, dict):
        raise InterAgentValidationError("Persisted orchestrator plans must be objects.")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise InterAgentValidationError("Orchestrator plan requires a non-empty tasks array.")
    if max_tasks is not None and len(raw_tasks) > max_tasks:
        raise InterAgentValidationError("Orchestrator plan exceeds the participant budget.")
    tasks = tuple(_task_spec(item) for item in raw_tasks)
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise InterAgentValidationError("Orchestrator plan task ids must be unique.")
    validate_task_ids_not_reserved(task_ids, reserved_task_ids=reserved_task_ids)
    _validate_task_references(tasks, set(task_ids))
    _assert_acyclic(tasks)
    if require_review_gate and not any(task.role in _REVIEWER_ROLES and task.review_of for task in tasks):
        raise InterAgentValidationError("Orchestrated plans require at least one implementer/reviewer quality gate.")
    summary = _bounded_text(payload.get("summary"), field="plan.summary", limit=1000)
    return OrchestrationPlan(summary=summary or f"Planned {len(tasks)} tasks.", tasks=tasks)


def parse_control_decision(
    value: str,
    *,
    existing_tasks: tuple[OrchestrationTaskSpec, ...],
    max_new_tasks: int,
    reserved_task_ids: set[str] | frozenset[str] = frozenset(),
) -> OrchestrationControlDecision:
    payload = _json_object(value, decision="control decision")
    return control_decision_from_payload(
        payload,
        existing_tasks=existing_tasks,
        max_new_tasks=max_new_tasks,
        reserved_task_ids=reserved_task_ids,
    )


def control_decision_from_payload(
    payload: Any,
    *,
    existing_tasks: tuple[OrchestrationTaskSpec, ...],
    max_new_tasks: int | None = None,
    reserved_task_ids: set[str] | frozenset[str] = frozenset(),
) -> OrchestrationControlDecision:
    """Rehydrate and validate one persisted orchestrator control decision."""
    if not isinstance(payload, dict):
        raise InterAgentValidationError("Persisted orchestrator control decisions must be objects.")
    raw_tasks = payload.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise InterAgentValidationError("Orchestrator control tasks must be an array.")
    if max_new_tasks is not None and len(raw_tasks) > max_new_tasks:
        raise InterAgentValidationError("Orchestrator control decision exceeds the remaining participant budget.")
    tasks = tuple(_task_spec(item) for item in raw_tasks)
    existing_ids = {task.task_id for task in existing_tasks}
    new_ids = [task.task_id for task in tasks]
    if len(new_ids) != len(set(new_ids)) or existing_ids.intersection(new_ids):
        raise InterAgentValidationError("Orchestrator control task ids must be new and unique.")
    validate_task_ids_not_reserved(new_ids, reserved_task_ids=reserved_task_ids)
    all_tasks = (*existing_tasks, *tasks)
    _validate_task_references(tasks, {task.task_id for task in all_tasks})
    _assert_acyclic(all_tasks)
    raw_cancel_ids = payload.get("cancel_task_ids", [])
    if not isinstance(raw_cancel_ids, list):
        raise InterAgentValidationError("Orchestrator cancel_task_ids must be an array.")
    cancel_ids = tuple(dict.fromkeys(str(item or "").strip() for item in raw_cancel_ids if str(item or "").strip()))
    unknown_cancel_ids = set(cancel_ids) - existing_ids
    if unknown_cancel_ids:
        raise InterAgentValidationError(
            f"Orchestrator cannot cancel unknown tasks: {', '.join(sorted(unknown_cancel_ids))}."
        )
    if not isinstance(payload.get("complete"), bool) or not isinstance(payload.get("quality_passed"), bool):
        raise InterAgentValidationError("Orchestrator control decision requires boolean complete and quality_passed.")
    summary = _bounded_text(payload.get("summary"), field="control.summary", limit=2000)
    final_answer = _bounded_text(payload.get("final_answer"), field="control.final_answer", limit=20000)
    if payload["complete"] and (not payload["quality_passed"] or not final_answer):
        raise InterAgentValidationError("A completed orchestration requires passing quality and a final answer.")
    if not payload["complete"] and payload["quality_passed"]:
        raise InterAgentValidationError("An incomplete orchestration cannot claim a passing final quality gate.")
    return OrchestrationControlDecision(
        summary=summary or "Continue orchestration.",
        tasks=tasks,
        cancel_task_ids=cancel_ids,
        complete=payload["complete"],
        quality_passed=payload["quality_passed"],
        final_answer=final_answer,
    )


def parse_review_decision(value: str) -> ReviewDecision:
    payload = _json_object(value, decision="review")
    if not isinstance(payload.get("approved"), bool):
        raise InterAgentValidationError("Reviewer decision requires boolean approved.")
    feedback = _bounded_text(payload.get("feedback"), field="review.feedback", limit=4000)
    if not payload["approved"] and not feedback:
        raise InterAgentValidationError("Rejected review decisions require feedback.")
    return ReviewDecision(approved=payload["approved"], feedback=feedback)


def parse_completion_decision(value: str) -> CompletionDecision:
    payload = _json_object(value, decision="completion")
    if not isinstance(payload.get("complete"), bool) or not isinstance(payload.get("quality_passed"), bool):
        raise InterAgentValidationError("Orchestrator completion requires boolean complete and quality_passed.")
    summary = _bounded_text(payload.get("summary"), field="completion.summary", limit=2000)
    final_answer = _bounded_text(payload.get("final_answer"), field="completion.final_answer", limit=20000)
    if payload["complete"] and (not payload["quality_passed"] or not final_answer):
        raise InterAgentValidationError("A completed orchestration requires passing quality and a final answer.")
    return CompletionDecision(
        complete=payload["complete"],
        quality_passed=payload["quality_passed"],
        summary=summary,
        final_answer=final_answer,
    )


def task_payload(task: OrchestrationTaskSpec) -> dict[str, Any]:
    return {
        "id": task.task_id,
        "label": task.label,
        "role": task.role,
        "objective": task.objective,
        "depends_on": list(task.depends_on),
        "review_of": task.review_of,
        "agent_type_id": task.agent_type_id,
    }


def task_spec_from_payload(
    value: Any,
    *,
    reserved_task_ids: set[str] | frozenset[str] = frozenset(),
) -> OrchestrationTaskSpec:
    task = _task_spec(value)
    validate_task_ids_not_reserved((task.task_id,), reserved_task_ids=reserved_task_ids)
    return task


def _task_spec(value: Any) -> OrchestrationTaskSpec:
    if not isinstance(value, dict):
        raise InterAgentValidationError("Orchestrator plan tasks must be objects.")
    task_id = str(value.get("id") or "").strip()
    if not _TASK_ID_RE.fullmatch(task_id):
        raise InterAgentValidationError("Orchestrator task ids must be safe lowercase identifiers.")
    role = str(value.get("role") or "").strip().lower()
    if role not in _ALLOWED_ROLES:
        raise InterAgentValidationError(f"Unsupported orchestrator task role `{role}`.")
    label = _bounded_text(value.get("label"), field=f"task.{task_id}.label", limit=160)
    objective = _bounded_text(value.get("objective"), field=f"task.{task_id}.objective", limit=4000)
    if not label or not objective:
        raise InterAgentValidationError("Orchestrator tasks require label and objective.")
    raw_dependencies = value.get("depends_on", [])
    if not isinstance(raw_dependencies, list):
        raise InterAgentValidationError("Orchestrator task depends_on must be an array.")
    dependencies = tuple(dict.fromkeys(str(item or "").strip() for item in raw_dependencies if str(item or "").strip()))
    review_of = str(value.get("review_of") or "").strip() or None
    agent_type_id = str(value.get("agent_type_id") or "").strip() or None
    if agent_type_id and not _AGENT_TYPE_ID_RE.fullmatch(agent_type_id):
        raise InterAgentValidationError(f"Task `{task_id}` has an invalid agent_type_id.")
    return OrchestrationTaskSpec(
        task_id=task_id,
        label=label,
        role=role,
        objective=objective,
        depends_on=dependencies,
        review_of=review_of,
        agent_type_id=agent_type_id,
    )


def _validate_task_references(tasks: tuple[OrchestrationTaskSpec, ...], known: set[str]) -> None:
    for task in tasks:
        unknown = set(task.depends_on) - known
        if unknown:
            raise InterAgentValidationError(
                f"Orchestrator task `{task.task_id}` has unknown dependencies: {', '.join(sorted(unknown))}."
            )
        if task.task_id in task.depends_on:
            raise InterAgentValidationError(f"Orchestrator task `{task.task_id}` cannot depend on itself.")
        if task.review_of and task.review_of not in known:
            raise InterAgentValidationError(f"Reviewer task `{task.task_id}` references an unknown review target.")


def _assert_acyclic(tasks: tuple[OrchestrationTaskSpec, ...]) -> None:
    dependencies = {task.task_id: set(task.depends_on) for task in tasks}
    resolved: set[str] = set()
    while len(resolved) < len(tasks):
        ready = {task_id for task_id, items in dependencies.items() if task_id not in resolved and items <= resolved}
        if not ready:
            raise InterAgentValidationError("Orchestrator plan dependency graph contains a cycle.")
        resolved.update(ready)


def _json_object(value: str, *, decision: str) -> dict[str, Any]:
    text = str(value or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        candidate = candidate[start : end + 1] if start >= 0 and end > start else candidate
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise InterAgentValidationError(f"Orchestrator {decision} must be one valid JSON object.") from exc
    if not isinstance(payload, dict):
        raise InterAgentValidationError(f"Orchestrator {decision} must be a JSON object.")
    return payload


def _bounded_text(value: Any, *, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise InterAgentValidationError(f"{field} must be {limit} characters or fewer.")
    return text
