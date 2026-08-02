"""Bounded prompt contracts for dynamic inter-agent orchestration."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from core.inter_agent.orchestration_plan import OrchestrationTaskSpec


class TaskResultLike(Protocol):
    status: str
    output_text: str


def planning_prompt(
    input_text: str,
    generalist_analysis: str,
    policy: str | None,
    directives: list[Any],
) -> str:
    return (
        "You are the sole orchestrator of a Maverick Agent nodes run. Produce only one JSON object with "
        'summary and tasks. Each task requires id, label, role, objective, depends_on; reviewer tasks also require review_of. '
        "Use safe lowercase ids. Include at least one implementer and a dependent reviewer. Do not execute the work yourself.\n\n"
        f"Policy: {policy or 'auto'}\nUser request:\n{input_text}\n\n"
        f"Generalist launch analysis:\n{generalist_analysis}\n{directive_block(directives)}"
    )


def task_prompt(task: OrchestrationTaskSpec, input_text: str, dependency_outputs: Mapping[str, str]) -> str:
    dependencies = "\n\n".join(
        f"Dependency {task_id}:\n{output[:8000]}" for task_id, output in dependency_outputs.items()
    )
    review_contract = (
        '\nReturn only JSON {"approved": boolean, "feedback": string}. Approve only if the result fully satisfies the request.'
        if task.role == "reviewer"
        else ""
    )
    return (
        f"You are the {task.role} worker `{task.task_id}` in a bounded orchestration.\n"
        f"Objective:\n{task.objective}\n\nUser request:\n{input_text}\n\n{dependencies}{review_contract}"
    ).strip()


def completion_prompt(
    input_text: str,
    results: Mapping[str, TaskResultLike],
    directives: list[Any],
) -> str:
    evidence = "\n\n".join(
        f"Task {task_id} ({result.status}):\n{result.output_text[:10000]}" for task_id, result in results.items()
    )
    return (
        "You are the sole orchestrator completion gate. Evaluate the persisted worker and reviewer evidence. "
        'Return only JSON {"complete": boolean, "quality_passed": boolean, "summary": string, "final_answer": string}. '
        "Only complete when quality passed. The final answer must be user-facing and must not narrate orchestration.\n\n"
        f"User request:\n{input_text}\n\nEvidence:\n{evidence}\n{directive_block(directives)}"
    )


def directive_block(directives: list[Any]) -> str:
    texts = [str(item.payload.get("text") or "").strip() for item in directives]
    texts = [text for text in texts if text]
    return "\n\nLive generalist/user directives:\n" + "\n".join(f"- {text}" for text in texts) if texts else ""
