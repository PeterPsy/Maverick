"""Validated structured decisions produced by a runtime orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from core.inter_agent.errors import InterAgentValidationError


_TASK_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ALLOWED_ROLES = {"implementer", "reviewer", "researcher", "analyst", "synthesizer"}


@dataclass(frozen=True)
class OrchestrationTaskSpec:
    task_id: str
    label: str
    role: str
    objective: str
    depends_on: tuple[str, ...] = ()
    review_of: str | None = None


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


def parse_orchestration_plan(value: str, *, max_tasks: int) -> OrchestrationPlan:
    payload = _json_object(value, decision="plan")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise InterAgentValidationError("Orchestrator plan requires a non-empty tasks array.")
    if len(raw_tasks) > max_tasks:
        raise InterAgentValidationError("Orchestrator plan exceeds the participant budget.")
    tasks = tuple(_task_spec(item) for item in raw_tasks)
    task_ids = [task.task_id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise InterAgentValidationError("Orchestrator plan task ids must be unique.")
    known = set(task_ids)
    for task in tasks:
        unknown = set(task.depends_on) - known
        if unknown:
            raise InterAgentValidationError(
                f"Orchestrator task `{task.task_id}` has unknown dependencies: {', '.join(sorted(unknown))}."
            )
        if task.task_id in task.depends_on:
            raise InterAgentValidationError(f"Orchestrator task `{task.task_id}` cannot depend on itself.")
        if task.review_of:
            if task.role != "reviewer":
                raise InterAgentValidationError("Only reviewer tasks may declare review_of.")
            if task.review_of not in known:
                raise InterAgentValidationError(f"Reviewer task `{task.task_id}` references an unknown review target.")
            if task.review_of not in task.depends_on:
                raise InterAgentValidationError("Reviewer tasks must depend on their review target.")
    _assert_acyclic(tasks)
    if not any(task.role == "reviewer" and task.review_of for task in tasks):
        raise InterAgentValidationError("Orchestrated plans require at least one implementer/reviewer quality gate.")
    summary = _bounded_text(payload.get("summary"), field="plan.summary", limit=1000)
    return OrchestrationPlan(summary=summary or f"Planned {len(tasks)} tasks.", tasks=tasks)


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
    raw_dependencies = value.get("depends_on")
    if raw_dependencies is None:
        raw_dependencies = []
    if not isinstance(raw_dependencies, list):
        raise InterAgentValidationError("Orchestrator task depends_on must be an array.")
    dependencies = tuple(dict.fromkeys(str(item or "").strip() for item in raw_dependencies if str(item or "").strip()))
    review_of = str(value.get("review_of") or "").strip() or None
    return OrchestrationTaskSpec(
        task_id=task_id,
        label=label,
        role=role,
        objective=objective,
        depends_on=dependencies,
        review_of=review_of,
    )


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
