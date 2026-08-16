"""Immutable worker materialization for adaptive orchestration tasks."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.models import (
    AgentParticipantSnapshot,
    InterAgentParticipantRecord,
    ParticipantSpec,
    validate_agent_snapshot,
)
from core.inter_agent.orchestration_plan import OrchestrationTaskSpec


AgentSnapshotResolver = Callable[[str], AgentParticipantSnapshot]


def worker_spec(
    orchestrator: InterAgentParticipantRecord,
    task: OrchestrationTaskSpec,
    *,
    participant_id: str,
    snapshot_resolver: AgentSnapshotResolver | None = None,
) -> ParticipantSpec:
    """Build server-owned worker material for a task that has not been persisted."""
    if task.agent_type_id and snapshot_resolver is not None:
        selected = snapshot_resolver(task.agent_type_id)
        if selected.agent_type_id != task.agent_type_id:
            raise InterAgentValidationError(
                f"Agent catalog returned `{selected.agent_type_id}` for requested task agent type "
                f"`{task.agent_type_id}`."
            )
        snapshot = replace(
            selected,
            metadata={
                **selected.metadata,
                "source": "server_agent_catalog",
                "role": task.role,
                "task_id": task.task_id,
            },
        )
        return _participant_spec(task, participant_id=participant_id, snapshot=snapshot)
    root_snapshot = _root_snapshot(orchestrator, task)
    if task.agent_type_id and task.agent_type_id != root_snapshot.agent_type_id:
        raise InterAgentValidationError(
            f"Task `{task.task_id}` requires catalog material for agent type `{task.agent_type_id}`."
        )
    return _participant_spec(task, participant_id=participant_id, snapshot=root_snapshot)


def validate_persisted_task_participant(
    orchestrator: InterAgentParticipantRecord,
    task: OrchestrationTaskSpec,
    participant: InterAgentParticipantRecord,
) -> None:
    """Fail closed unless a persisted participant is the immutable worker for this task."""
    if participant.kind != "agent" or participant.execution_mode != "child_runtime_session":
        raise _material_error(task, "kind or execution mode")
    if participant.label != task.label or participant.thread_visibility != "hidden":
        raise _material_error(task, "label or visibility")
    if participant.prompt_snapshot_ref is not None or participant.authority_grant_ids:
        raise _material_error(task, "authority material")
    document = participant.agent_snapshot
    if not isinstance(document, dict):
        raise _material_error(task, "agent snapshot")
    snapshot = _snapshot_from_document(task, document)
    snapshot_digest = _snapshot_digest(task, snapshot)
    if participant.agent_snapshot_digest != snapshot_digest or document.get("digest") != snapshot_digest:
        raise _material_error(task, "agent snapshot digest")
    root_agent_type_id = _root_agent_type_id(orchestrator)
    expected_agent_type_id = task.agent_type_id or root_agent_type_id
    source = str(snapshot.metadata.get("source") or "")
    if source == "orchestrator_server_snapshot" and expected_agent_type_id != root_agent_type_id:
        raise _material_error(task, "agent type source")
    if participant.agent_type_id != expected_agent_type_id or snapshot.agent_type_id != expected_agent_type_id:
        raise _material_error(task, "agent type")
    if participant.skill_ids != snapshot.skill_ids or participant.provider_id != snapshot.provider_id:
        raise _material_error(task, "snapshot-derived runtime material")


def _participant_spec(
    task: OrchestrationTaskSpec,
    *,
    participant_id: str,
    snapshot: AgentParticipantSnapshot,
) -> ParticipantSpec:
    return ParticipantSpec(
        participant_id=participant_id,
        kind="agent",
        execution_mode="child_runtime_session",
        label=task.label,
        agent_type_id=snapshot.agent_type_id,
        agent_snapshot=snapshot,
    )


def _root_snapshot(
    orchestrator: InterAgentParticipantRecord,
    task: OrchestrationTaskSpec,
) -> AgentParticipantSnapshot:
    document = orchestrator.agent_snapshot if isinstance(orchestrator.agent_snapshot, dict) else {}
    return AgentParticipantSnapshot(
        agent_type_id=_root_agent_type_id(orchestrator),
        label=str(document.get("label") or orchestrator.label),
        system_prompt=str(document.get("system_prompt") or ""),
        skill_ids=[str(item) for item in document.get("skill_ids", []) if str(item).strip()],
        skill_catalog_app_id=str(document.get("skill_catalog_app_id") or "skills"),
        skill_activation_mode=str(document.get("skill_activation_mode") or "implicit"),
        provider_id=str(document.get("provider_id") or "").strip() or orchestrator.provider_id,
        revision_id=str(document.get("revision_id") or "").strip() or None,
        metadata={
            "source": "orchestrator_server_snapshot",
            "role": task.role,
            "task_id": task.task_id,
        },
    )


def _snapshot_from_document(
    task: OrchestrationTaskSpec,
    document: dict[str, object],
) -> AgentParticipantSnapshot:
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise _material_error(task, "agent snapshot metadata")
    if metadata.get("task_id") != task.task_id or metadata.get("role") != task.role:
        raise _material_error(task, "task-bound snapshot metadata")
    if metadata.get("source") not in {"server_agent_catalog", "orchestrator_server_snapshot"}:
        raise _material_error(task, "server materialization source")
    skill_ids = document.get("skill_ids")
    return AgentParticipantSnapshot(
        agent_type_id=str(document.get("agent_type_id") or ""),
        label=str(document.get("label") or ""),
        system_prompt=str(document.get("system_prompt") or ""),
        skill_ids=[str(item) for item in skill_ids] if isinstance(skill_ids, list) else [],
        skill_catalog_app_id=str(document.get("skill_catalog_app_id") or ""),
        skill_activation_mode=str(document.get("skill_activation_mode") or "implicit"),
        provider_id=str(document.get("provider_id") or "").strip() or None,
        revision_id=str(document.get("revision_id") or "").strip() or None,
        metadata=metadata,
    )


def _snapshot_digest(task: OrchestrationTaskSpec, snapshot: AgentParticipantSnapshot) -> str:
    try:
        validate_agent_snapshot(snapshot)
        return snapshot.digest()
    except Exception as exc:
        raise _material_error(task, "agent snapshot digest") from exc


def _root_agent_type_id(orchestrator: InterAgentParticipantRecord) -> str:
    document = orchestrator.agent_snapshot if isinstance(orchestrator.agent_snapshot, dict) else {}
    return str(document.get("agent_type_id") or orchestrator.agent_type_id or "orchestrator")


def _material_error(task: OrchestrationTaskSpec, field: str) -> InterAgentValidationError:
    return InterAgentValidationError(
        f"Persisted participant `{task.task_id}` does not match materialized task {field}."
    )
