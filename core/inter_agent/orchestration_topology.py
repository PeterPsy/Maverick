"""Fail-closed topology identity rules for dynamic orchestration."""

from __future__ import annotations

from collections.abc import Iterable

from core.inter_agent.errors import InterAgentValidationError


RESERVED_ORCHESTRATION_TASK_IDS = frozenset({"orchestrator"})


def reserved_task_ids_for_run(orchestrator_participant_id: str) -> frozenset[str]:
    """Return task ids that untrusted orchestrator output may never claim."""
    participant_id = str(orchestrator_participant_id or "").strip()
    if not participant_id:
        return RESERVED_ORCHESTRATION_TASK_IDS
    return RESERVED_ORCHESTRATION_TASK_IDS.union({participant_id})


def validate_task_ids_not_reserved(
    task_ids: Iterable[str],
    *,
    reserved_task_ids: set[str] | frozenset[str],
) -> None:
    reserved = RESERVED_ORCHESTRATION_TASK_IDS.union(
        str(task_id or "").strip() for task_id in reserved_task_ids if str(task_id or "").strip()
    )
    collisions = sorted(task_id for task_id in task_ids if task_id in reserved)
    if collisions:
        raise InterAgentValidationError(
            f"Orchestrator task ids are reserved participant ids: {', '.join(collisions)}."
        )
