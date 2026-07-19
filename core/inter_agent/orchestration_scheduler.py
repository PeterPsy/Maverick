"""Core-owned dynamic dependency scheduler for orchestrated runs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Callable

from core.inter_agent.errors import InterAgentOperationError, InterAgentValidationError
from core.inter_agent.models import AgentParticipantSnapshot, EdgeSpec, InterAgentParticipantRecord, ParticipantSpec
from core.inter_agent.orchestration_plan import (
    OrchestrationPlan,
    OrchestrationTaskSpec,
    parse_completion_decision,
    parse_orchestration_plan,
    parse_review_decision,
)
from core.inter_agent.service import InterAgentService


ParticipantTurnExecutor = Callable[[InterAgentParticipantRecord, str, str], str]
GENERALIST_DIRECTIVE_EVENT_TYPES = {
    "runtime.output.final",
    "runtime.step.updated",
    "runtime.tool_call.completed",
}


@dataclass(frozen=True)
class OrchestrationTaskResult:
    task_id: str
    participant_id: str
    status: str
    output_text: str = ""
    error: str | None = None


@dataclass(frozen=True)
class OrchestrationExecutionResult:
    run: Any
    task_results: tuple[OrchestrationTaskResult, ...]
    final_answer: str = ""


def execute_orchestrated_run(
    service: InterAgentService,
    state: Any,
    *,
    workspace_id: str,
    run_id: str,
    input_text: str,
    turn_executor: ParticipantTurnExecutor | None = None,
    now: datetime | None = None,
) -> OrchestrationExecutionResult:
    """Plan, materialize, schedule, review, and complete one dynamic run."""
    run = service.store.get_run(run_id, workspace_id=workspace_id)
    if run.mode != "orchestrated":
        raise InterAgentOperationError("Dynamic scheduler requires an orchestrated run.")
    if run.status in {"completed", "failed", "cancelled"}:
        return OrchestrationExecutionResult(run=run, task_results=())
    timestamp = now or datetime.now(tz=UTC)
    run = replace(run, status="planning", updated_at=timestamp)
    service.store.save_run(run)
    orchestrator = service.store.get_participant(
        run.orchestrator_participant_id,
        workspace_id=workspace_id,
        run_id=run.run_id,
    )
    execute_turn = turn_executor or _runtime_turn_executor(service, state, run)
    try:
        _sync_generalist_directives(service, state, run)
        planning_directives = service.pending_directives(run)
        plan_output = execute_turn(
            orchestrator,
            _planning_prompt(input_text, run.orchestration_policy, planning_directives),
            f"{run.run_id}:orchestrator:plan",
        )
        service.mark_directives_delivered(run, planning_directives)
        budget = service.store.get_budget_policy(run.budget_policy_id, workspace_id=workspace_id)
        revision_slots = 2 * max(0, budget.max_rounds - 1)
        max_initial_tasks = budget.max_participants - 1 - revision_slots
        if max_initial_tasks < 2:
            raise InterAgentValidationError("Orchestration budget cannot reserve an implementer/reviewer revision loop.")
        plan = parse_orchestration_plan(plan_output, max_tasks=max_initial_tasks)
        _record_plan(service, run, plan)
        task_participants = _materialize_plan(service, run, orchestrator, plan)
        run = replace(run, status="running", updated_at=datetime.now(tz=UTC))
        service.store.save_run(run)
        results = _execute_dependency_graph(
            service,
            run,
            plan,
            task_participants,
            input_text=input_text,
            execute_turn=execute_turn,
            max_concurrency=budget.max_concurrent_participants,
        )
        results = _run_review_revisions(
            service,
            run,
            plan,
            orchestrator,
            results,
            input_text=input_text,
            execute_turn=execute_turn,
            max_rounds=budget.max_rounds,
        )
        _sync_generalist_directives(service, state, run)
        completion_directives = service.pending_directives(run)
        completion_output = execute_turn(
            orchestrator,
            _completion_prompt(input_text, results, completion_directives),
            f"{run.run_id}:orchestrator:completion",
        )
        service.mark_directives_delivered(run, completion_directives)
        decision = parse_completion_decision(completion_output)
        completed = service.decide_completion(
            workspace_id=workspace_id,
            run_id=run.run_id,
            participant_id=orchestrator.participant_id,
            complete=decision.complete,
            quality_passed=decision.quality_passed,
            summary=decision.summary,
            final_answer=decision.final_answer,
        )
        if not decision.complete:
            raise InterAgentOperationError("Orchestrator requested revision after the configured review rounds.")
        service.release_budget(completed, reservation_id=f"spawn:{orchestrator.participant_id}")
        return OrchestrationExecutionResult(
            run=completed,
            task_results=tuple(results.values()),
            final_answer=decision.final_answer,
        )
    except Exception as error:
        latest = service.store.get_run(run.run_id, workspace_id=workspace_id)
        if latest.status not in {"completed", "cancelled", "failed"}:
            latest = replace(latest, status="failed", updated_at=datetime.now(tz=UTC), ended_at=datetime.now(tz=UTC))
            service.store.save_run(latest)
            service.record_event(
                latest,
                event_type="inter_agent.run.failed",
                participant_id=latest.orchestrator_participant_id,
                visibility_plane="summary",
                correlation_id=latest.run_id,
                idempotency_key=f"{latest.run_id}:dynamic.failed",
                payload={"status": "failed", "error": str(error)},
            )
        if isinstance(error, (InterAgentOperationError, InterAgentValidationError)):
            raise
        raise InterAgentOperationError(str(error)) from error


def _materialize_plan(
    service: InterAgentService,
    run: Any,
    orchestrator: InterAgentParticipantRecord,
    plan: OrchestrationPlan,
) -> dict[str, InterAgentParticipantRecord]:
    participants: dict[str, InterAgentParticipantRecord] = {}
    for task in plan.tasks:
        participants[task.task_id] = service.add_participant(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            spec=_worker_spec(orchestrator, task, participant_id=task.task_id),
        )
    for task in plan.tasks:
        if not task.depends_on:
            service.add_edge(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                spec=EdgeSpec(
                    source_id=orchestrator.participant_id,
                    target_id=task.task_id,
                    kind="delegated",
                    label=task.objective[:160],
                ),
            )
        for dependency in task.depends_on:
            service.add_edge(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                spec=EdgeSpec(
                    source_id=dependency,
                    target_id=task.task_id,
                    kind="reviewed_by" if task.review_of == dependency else "depends_on",
                    label="Quality review" if task.review_of == dependency else "Dependency",
                ),
            )
    return participants


def _execute_dependency_graph(
    service: InterAgentService,
    run: Any,
    plan: OrchestrationPlan,
    participants: dict[str, InterAgentParticipantRecord],
    *,
    input_text: str,
    execute_turn: ParticipantTurnExecutor,
    max_concurrency: int,
) -> dict[str, OrchestrationTaskResult]:
    pending = {task.task_id: task for task in plan.tasks}
    results: dict[str, OrchestrationTaskResult] = {}
    while pending:
        ready = [task for task in pending.values() if set(task.depends_on) <= set(results)]
        if not ready:
            raise InterAgentOperationError("No dependency-ready orchestration tasks remain.")
        with ThreadPoolExecutor(max_workers=max(1, min(max_concurrency, len(ready)))) as pool:
            futures = {
                pool.submit(
                    _execute_task,
                    service,
                    run,
                    task,
                    participants[task.task_id],
                    input_text,
                    {dependency: results[dependency].output_text for dependency in task.depends_on},
                    execute_turn,
                ): task
                for task in ready
            }
            for future in as_completed(futures):
                task = futures[future]
                result = future.result()
                results[task.task_id] = result
                pending.pop(task.task_id, None)
                if result.status != "completed":
                    raise InterAgentOperationError(result.error or f"Task `{task.task_id}` failed.")
    return results


def _run_review_revisions(
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
                spec=_worker_spec(orchestrator, revision_task, participant_id=revision_id),
            )
            reviewer_participant = service.add_participant(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                spec=_worker_spec(orchestrator, revision_reviewer, participant_id=revision_review_id),
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
            implementation_result = _execute_task(
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
            reviewer_result = _execute_task(
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


def _execute_task(
    service: InterAgentService,
    run: Any,
    task: OrchestrationTaskSpec,
    participant: InterAgentParticipantRecord,
    input_text: str,
    dependency_outputs: dict[str, str],
    execute_turn: ParticipantTurnExecutor,
) -> OrchestrationTaskResult:
    now = datetime.now(tz=UTC)
    service.store.save_participant(replace(participant, status="running", current_task_id=task.task_id, updated_at=now))
    service.record_event(
        run,
        event_type="inter_agent.task.created",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task.task_id,
        idempotency_key=f"{run.run_id}:dynamic.task.created:{task.task_id}",
        payload={
            "task_id": task.task_id,
            "participant_id": participant.participant_id,
            "role": task.role,
            "objective": task.objective,
            "depends_on": list(task.depends_on),
            "review_of": task.review_of,
        },
    )
    service.record_event(
        run,
        event_type="inter_agent.task.started",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task.task_id,
        idempotency_key=f"{run.run_id}:dynamic.task.started:{task.task_id}",
        payload={"task_id": task.task_id, "participant_id": participant.participant_id},
    )
    try:
        output = execute_turn(
            participant,
            _task_prompt(task, input_text, dependency_outputs),
            f"{run.run_id}:task:{task.task_id}",
        ).strip()
        if not output:
            raise InterAgentOperationError(f"Task `{task.task_id}` returned no output.")
        status = "completed"
        error = None
    except Exception as exc:
        output = ""
        status = "failed"
        error = str(exc)
    finished_at = datetime.now(tz=UTC)
    latest = service.store.get_participant(
        participant.participant_id,
        workspace_id=run.workspace_id,
        run_id=run.run_id,
    )
    service.store.save_participant(replace(latest, status=status, current_task_id=None, updated_at=finished_at))
    service.release_budget(run, reservation_id=f"spawn:{participant.participant_id}")
    service.record_event(
        run,
        event_type="inter_agent.task.completed",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task.task_id,
        idempotency_key=f"{run.run_id}:dynamic.task.completed:{task.task_id}",
        payload={
            "task_id": task.task_id,
            "participant_id": participant.participant_id,
            "status": status,
            "summary": output[:1000],
            "output_text": output,
            "error": error,
        },
    )
    return OrchestrationTaskResult(
        task_id=task.task_id,
        participant_id=participant.participant_id,
        status=status,
        output_text=output,
        error=error,
    )


def _runtime_turn_executor(service: InterAgentService, state: Any, run: Any) -> ParticipantTurnExecutor:
    def execute(participant: InterAgentParticipantRecord, prompt: str, client_message_id: str) -> str:
        current = service.store.get_participant(
            participant.participant_id,
            workspace_id=run.workspace_id,
            run_id=run.run_id,
        )
        if not current.runtime_session_id:
            current, _session, _created = service.spawn_participant_runtime_session(
                state.runtime_store,
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                participant_id=current.participant_id,
                owner_user_id=run.created_by_user_id,
                created_by_user_id=run.created_by_user_id,
            )
        current, _turn, events = service.send_runtime_message(
            state,
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            participant_id=current.participant_id,
            input_text=prompt,
            client_message_id=client_message_id,
            async_requested=False,
        )
        output = _runtime_output_text(events)
        if not output:
            raise InterAgentOperationError(f"Participant `{current.participant_id}` returned no final output.")
        return output

    return execute


def _sync_generalist_directives(service: InterAgentService, state: Any, run: Any) -> None:
    runtime_store = getattr(state, "runtime_store", None)
    if runtime_store is None or not run.source_runtime_turn_id:
        return
    for event in runtime_store.list_events(run.root_runtime_session_id):
        if event.turn_id != run.source_runtime_turn_id or event.event_type not in GENERALIST_DIRECTIVE_EVENT_TYPES:
            continue
        text = _runtime_event_text(event)
        if not text:
            continue
        service.record_directive(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            text=text[:6000],
            source_kind="root_generalist",
            source_runtime_event_id=event.event_id,
            source_runtime_turn_id=run.source_runtime_turn_id,
            idempotency_key=f"{run.run_id}:root-directive:{event.event_id}",
        )


def _worker_spec(
    orchestrator: InterAgentParticipantRecord,
    task: OrchestrationTaskSpec,
    *,
    participant_id: str,
) -> ParticipantSpec:
    snapshot_document = orchestrator.agent_snapshot if isinstance(orchestrator.agent_snapshot, dict) else {}
    snapshot = AgentParticipantSnapshot(
        agent_type_id=str(snapshot_document.get("agent_type_id") or orchestrator.agent_type_id or "orchestrator"),
        label=str(snapshot_document.get("label") or orchestrator.label),
        system_prompt=str(snapshot_document.get("system_prompt") or ""),
        skill_ids=[str(item) for item in snapshot_document.get("skill_ids", []) if str(item).strip()],
        skill_catalog_app_id=str(snapshot_document.get("skill_catalog_app_id") or "skills"),
        provider_id=str(snapshot_document.get("provider_id") or "").strip() or orchestrator.provider_id,
        revision_id=str(snapshot_document.get("revision_id") or "").strip() or None,
        metadata={"source": "orchestrator_server_snapshot", "role": task.role},
    )
    return ParticipantSpec(
        participant_id=participant_id,
        kind="agent",
        execution_mode="child_runtime_session",
        label=task.label,
        agent_type_id=snapshot.agent_type_id,
        agent_snapshot=snapshot,
    )


def _record_plan(service: InterAgentService, run: Any, plan: OrchestrationPlan) -> None:
    service.record_event(
        run,
        event_type="inter_agent.plan.summary_created",
        participant_id=run.orchestrator_participant_id,
        visibility_plane="summary",
        correlation_id=f"{run.run_id}:dynamic-plan",
        idempotency_key=f"{run.run_id}:dynamic.plan",
        payload={
            "summary": plan.summary,
            "task_count": len(plan.tasks),
            "task_ids": [task.task_id for task in plan.tasks],
        },
    )


def _planning_prompt(input_text: str, policy: str | None, directives: list[Any]) -> str:
    return (
        "You are the sole orchestrator of a Maverick Agent nodes run. Produce only one JSON object with "
        'summary and tasks. Each task requires id, label, role, objective, depends_on; reviewer tasks also require review_of. '
        "Use safe lowercase ids. Include at least one implementer and a dependent reviewer. Do not execute the work yourself.\n\n"
        f"Policy: {policy or 'auto'}\nUser request:\n{input_text}\n{_directive_block(directives)}"
    )


def _task_prompt(task: OrchestrationTaskSpec, input_text: str, dependency_outputs: dict[str, str]) -> str:
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


def _completion_prompt(input_text: str, results: dict[str, OrchestrationTaskResult], directives: list[Any]) -> str:
    evidence = "\n\n".join(
        f"Task {task_id} ({result.status}):\n{result.output_text[:10000]}" for task_id, result in results.items()
    )
    return (
        "You are the sole orchestrator completion gate. Evaluate the persisted worker and reviewer evidence. "
        'Return only JSON {"complete": boolean, "quality_passed": boolean, "summary": string, "final_answer": string}. '
        "Only complete when quality passed. The final answer must be user-facing and must not narrate orchestration.\n\n"
        f"User request:\n{input_text}\n\nEvidence:\n{evidence}\n{_directive_block(directives)}"
    )


def _directive_block(directives: list[Any]) -> str:
    texts = [str(item.payload.get("text") or "").strip() for item in directives]
    texts = [text for text in texts if text]
    return "\n\nLive generalist/user directives:\n" + "\n".join(f"- {text}" for text in texts) if texts else ""


def _runtime_output_text(events: list[Any]) -> str:
    final = ""
    for event in events:
        if getattr(event, "event_type", "") != "runtime.output.final":
            continue
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        text = payload.get("complete_text") or payload.get("text")
        if isinstance(text, str) and text.strip():
            final = text.strip()
    return final


def _runtime_event_text(event: Any) -> str:
    payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
    for key in ("complete_text", "text", "summary", "label", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
