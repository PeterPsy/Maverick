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
    available_agent_types: list[str] | None = None,
) -> str:
    catalog = ", ".join(available_agent_types or []) or "default orchestrator capability"
    return (
        "You are the sole orchestrator of a Maverick Agent nodes run. Produce only one JSON object with "
        'summary and tasks. Each task requires id, label, role, objective, depends_on and may select agent_type_id; '
        "reviewer tasks also require review_of. Use safe lowercase ids. Plan only the work that is ready to start; "
        "you may add more tasks after every worker output. A reviewer must approve before completion. "
        "Never use orchestrator as a task id. "
        "Do not execute the work yourself.\n\n"
        f"Policy: {policy or 'auto'}\nUser request:\n{input_text}\n\n"
        f"Generalist launch analysis:\n{generalist_analysis}\n\nAvailable agent types: {catalog}"
        f"\n{directive_block(directives)}"
    )


def task_prompt(task: OrchestrationTaskSpec, input_text: str, dependency_outputs: Mapping[str, str]) -> str:
    dependencies = "\n\n".join(
        f"Dependency {task_id}:\n{output[:8000]}" for task_id, output in dependency_outputs.items()
    )
    review_contract = (
        '\nReturn only JSON {"approved": boolean, "feedback": string}. Approve only if the result fully satisfies the request.'
        if task.role in {"reviewer", "security_reviewer"}
        else ""
    )
    return (
        f"You are the {task.role} worker `{task.task_id}` in a bounded orchestration.\n"
        f"Objective:\n{task.objective}\n\nUser request:\n{input_text}\n\n{dependencies}{review_contract}"
    ).strip()


def control_prompt(
    input_text: str,
    tasks: tuple[OrchestrationTaskSpec, ...],
    results: Mapping[str, TaskResultLike],
    *,
    trigger_task_id: str | None,
    directives: list[Any],
    available_agent_types: list[str] | None = None,
) -> str:
    ledger = "\n".join(
        _task_ledger_line(task, results.get(task.task_id))
        for task in tasks
    )
    trigger = results.get(trigger_task_id or "")
    trigger_output = trigger.output_text[:10000] if trigger is not None else "No new worker output; inspect the ledger."
    catalog = ", ".join(available_agent_types or []) or "default orchestrator capability"
    return (
        "You are the sole adaptive orchestrator at a persisted scheduling safe point. Respond with one JSON object: "
        '{"summary": string, "tasks": array, "cancel_task_ids": array, "complete": boolean, '
        '"quality_passed": boolean, "final_answer": string}. New tasks use id, label, role, objective, '
        "depends_on and optional agent_type_id; reviewers also use review_of. Add work when evidence is insufficient, "
        "cancel only unnecessary unstarted work, and complete only after a dependent reviewer explicitly approved. "
        "Never use orchestrator as a task id. A rejected review remains blocking until revision work and a later "
        "approved review depend transitively on that rejection. "
        "When continuing without new work, return empty tasks and cancel_task_ids.\n\n"
        f"User request:\n{input_text}\n\nAvailable agent types: {catalog}\n\nTask ledger:\n{ledger}\n\n"
        f"Safe-point trigger: {trigger_task_id or 'scheduler'}\nLatest output:\n{trigger_output}"
        f"\n{directive_block(directives)}"
    )
def directive_block(directives: list[Any]) -> str:
    texts = [str(item.payload.get("text") or "").strip() for item in directives]
    texts = [text for text in texts if text]
    return "\n\nLive generalist/user directives:\n" + "\n".join(f"- {text}" for text in texts) if texts else ""


def _task_ledger_line(task: OrchestrationTaskSpec, result: TaskResultLike | None) -> str:
    status = result.status if result is not None else "pending"
    output = result.output_text[:1200].replace("\n", " ") if result is not None else ""
    dependencies = ",".join(task.depends_on) or "none"
    return f"- {task.task_id} role={task.role} status={status} depends_on={dependencies} output={output}"
