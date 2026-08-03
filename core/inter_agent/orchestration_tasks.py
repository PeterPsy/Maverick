"""Dynamic participant materialization and dependency-ready task execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.models import AgentParticipantSnapshot, EdgeSpec, InterAgentParticipantRecord, ParticipantSpec
from core.inter_agent.orchestration_plan import (
    OrchestrationPlan,
    OrchestrationTaskSpec,
    task_payload,
)
from core.inter_agent.orchestration_prompts import task_prompt
from core.inter_agent.orchestration_runtime import ParticipantTurnExecutor
from core.inter_agent.service import InterAgentService


@dataclass(frozen=True)
class OrchestrationTaskResult:
    task_id: str
    participant_id: str
    status: str
    output_text: str = ""
    error: str | None = None


AgentSnapshotResolver = Callable[[str], AgentParticipantSnapshot]


def materialize_plan(
    service: InterAgentService,
    run: Any,
    orchestrator: InterAgentParticipantRecord,
    plan: OrchestrationPlan,
    *,
    snapshot_resolver: AgentSnapshotResolver | None = None,
) -> dict[str, InterAgentParticipantRecord]:
    return materialize_tasks(
        service,
        run,
        orchestrator,
        plan.tasks,
        snapshot_resolver=snapshot_resolver,
    )


def materialize_tasks(
    service: InterAgentService,
    run: Any,
    orchestrator: InterAgentParticipantRecord,
    tasks: tuple[OrchestrationTaskSpec, ...],
    *,
    snapshot_resolver: AgentSnapshotResolver | None = None,
) -> dict[str, InterAgentParticipantRecord]:
    participants: dict[str, InterAgentParticipantRecord] = {}
    persisted_participants = {
        participant.participant_id: participant
        for participant in service.store.list_participants(run.run_id, workspace_id=run.workspace_id)
    }
    for task in tasks:
        participant = persisted_participants.get(task.task_id)
        if participant is None:
            participant = service.add_participant(
                workspace_id=run.workspace_id,
                run_id=run.run_id,
                spec=worker_spec(
                    orchestrator,
                    task,
                    participant_id=task.task_id,
                    snapshot_resolver=snapshot_resolver,
                ),
            )
            persisted_participants[task.task_id] = participant
        participants[task.task_id] = participant
        service.record_event(
            run,
            event_type="inter_agent.task.created",
            participant_id=task.task_id,
            visibility_plane="detail",
            correlation_id=task.task_id,
            idempotency_key=f"{run.run_id}:dynamic.task.created:{task.task_id}",
            payload={
                "task_id": task.task_id,
                "participant_id": task.task_id,
                "attempt": 1,
                "task": task_payload(task),
            },
        )
    for task in tasks:
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


def execute_task(
    service: InterAgentService,
    run: Any,
    task: OrchestrationTaskSpec,
    participant: InterAgentParticipantRecord,
    input_text: str,
    dependency_outputs: Mapping[str, str],
    execute_turn: ParticipantTurnExecutor,
) -> OrchestrationTaskResult:
    now = datetime.now(tz=UTC)
    service.store.save_participant(replace(participant, status="running", current_task_id=task.task_id, updated_at=now))
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
            task_prompt(task, input_text, dependency_outputs),
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


def worker_spec(
    orchestrator: InterAgentParticipantRecord,
    task: OrchestrationTaskSpec,
    *,
    participant_id: str,
    snapshot_resolver: AgentSnapshotResolver | None = None,
) -> ParticipantSpec:
    if task.agent_type_id and snapshot_resolver is not None:
        selected = snapshot_resolver(task.agent_type_id)
        snapshot = replace(
            selected,
            metadata={**selected.metadata, "source": "server_agent_catalog", "role": task.role},
        )
        return ParticipantSpec(
            participant_id=participant_id,
            kind="agent",
            execution_mode="child_runtime_session",
            label=task.label,
            agent_type_id=snapshot.agent_type_id,
            agent_snapshot=snapshot,
        )
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


def record_plan(service: InterAgentService, run: Any, plan: OrchestrationPlan) -> None:
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
            "tasks": [task_payload(task) for task in plan.tasks],
        },
    )


def cancel_task(
    service: InterAgentService,
    run: Any,
    task: OrchestrationTaskSpec,
    participant: InterAgentParticipantRecord,
) -> OrchestrationTaskResult:
    now = datetime.now(tz=UTC)
    latest = service.store.get_participant(
        participant.participant_id,
        workspace_id=run.workspace_id,
        run_id=run.run_id,
    )
    if latest.status not in {"completed", "failed", "cancelled"}:
        service.store.save_participant(replace(latest, status="cancelled", current_task_id=None, updated_at=now))
        service.release_budget(run, reservation_id=f"spawn:{participant.participant_id}")
    service.record_event(
        run,
        event_type="inter_agent.task.completed",
        participant_id=participant.participant_id,
        visibility_plane="detail",
        correlation_id=task.task_id,
        idempotency_key=f"{run.run_id}:dynamic.task.cancelled:{task.task_id}",
        payload={
            "task_id": task.task_id,
            "participant_id": participant.participant_id,
            "status": "cancelled",
            "summary": "Cancelled by orchestrator decision.",
            "output_text": "",
            "error": None,
        },
    )
    return OrchestrationTaskResult(
        task_id=task.task_id,
        participant_id=participant.participant_id,
        status="cancelled",
    )
