"""Handoff event projection for the MAF adapter."""

from __future__ import annotations

from typing import Any

from core.inter_agent.adapters.base import AdapterEventMappingContext
from core.inter_agent.adapters.shared import (
    _adapter_event_identity_token,
    _clean_optional,
    _created_at,
    _safe_output_summary,
    _value,
    _workflow_source_event_id,
)
from core.inter_agent.events import (
    InterAgentEventRecord,
    InterAgentEventType,
    InterAgentVisibilityPlane,
    validate_event_record,
)


_HANDOFF_EVENT_TYPES: dict[str, InterAgentEventType] = {
    "handoff_sent": "inter_agent.handoff.requested",
    "handoff_requested": "inter_agent.handoff.requested",
    "handoff_request": "inter_agent.handoff.requested",
    "handoff_accepted": "inter_agent.handoff.accepted",
    "handoff_accept": "inter_agent.handoff.accepted",
    "handoff_completed": "inter_agent.handoff.completed",
    "handoff_complete": "inter_agent.handoff.completed",
}


def handoff_records(
    context: AdapterEventMappingContext,
    event: object,
    *,
    adapter_event_type: str,
    pending_handoffs: dict[str, str | None],
    visibility_plane: InterAgentVisibilityPlane,
    source_index: int,
    mapped_index: int,
) -> list[InterAgentEventRecord]:
    """Project one MAF handoff event when it belongs to the handoff lifecycle."""
    event_type = _HANDOFF_EVENT_TYPES.get(adapter_event_type)
    if event_type is None:
        derived = _derived_handoff_event(event, adapter_event_type, pending_handoffs, source_index)
        if derived is None:
            return []
        event, event_type, adapter_event_type = derived
    source_participant_id = _clean_optional(
        _value(event, "source_participant_id", "source", "from_agent", "from_participant")
    )
    target_participant_id = _clean_optional(
        _value(event, "target_participant_id", "target", "to_agent", "to_participant")
    )
    if event_type == "inter_agent.handoff.requested" and target_participant_id:
        pending_handoffs[target_participant_id] = source_participant_id
    return [
        _handoff_record(
            context,
            event,
            adapter_event_type=adapter_event_type,
            event_type=event_type,
            visibility_plane=visibility_plane,
            mapped_index=mapped_index,
        )
    ]


def _derived_handoff_event(
    event: object,
    adapter_event_type: str,
    pending_handoffs: dict[str, str | None],
    source_index: int,
) -> tuple[dict[str, Any], InterAgentEventType, str] | None:
    if adapter_event_type == "executor_invoked":
        target_participant_id = _clean_optional(_value(event, "executor_id", "target_participant_id", "target"))
        if not target_participant_id or target_participant_id not in pending_handoffs:
            return None
        if _value(event, "should_respond") is not True:
            return None
        return (
            {
                "source_event_id": _workflow_source_event_id(event, adapter_event_type, source_index),
                "source_participant_id": pending_handoffs[target_participant_id],
                "target_participant_id": target_participant_id,
                "summary": "MAF invoked the handoff target participant.",
                "correlation_id": _handoff_correlation_id(
                    pending_handoffs[target_participant_id],
                    target_participant_id,
                ),
            },
            "inter_agent.handoff.accepted",
            adapter_event_type,
        )
    if adapter_event_type == "output":
        target_participant_id = _clean_optional(_value(event, "executor_id", "target_participant_id", "target"))
        if not target_participant_id or target_participant_id not in pending_handoffs:
            return None
        return (
            {
                "source_event_id": _workflow_source_event_id(event, adapter_event_type, source_index),
                "source_participant_id": pending_handoffs[target_participant_id],
                "target_participant_id": target_participant_id,
                "summary": _safe_output_summary(event)
                or "MAF handoff target participant produced output.",
                "correlation_id": _handoff_correlation_id(
                    pending_handoffs[target_participant_id],
                    target_participant_id,
                ),
            },
            "inter_agent.handoff.completed",
            adapter_event_type,
        )
    return None

def _handoff_record(
    context: AdapterEventMappingContext,
    event: object,
    *,
    adapter_event_type: str,
    event_type: InterAgentEventType,
    visibility_plane: InterAgentVisibilityPlane,
    mapped_index: int,
) -> InterAgentEventRecord:
    run = context.run
    source_participant_id = _clean_optional(
        _value(event, "source_participant_id", "source", "from_agent", "from_participant")
    )
    target_participant_id = _clean_optional(
        _value(event, "target_participant_id", "target", "to_agent", "to_participant")
    )
    source_event_id = _clean_optional(_value(event, "source_event_id", "event_id", "id"))
    participant_id = source_participant_id
    if event_type in {"inter_agent.handoff.accepted", "inter_agent.handoff.completed"}:
        participant_id = target_participant_id or source_participant_id
    payload = _safe_handoff_payload(
        event,
        adapter_event_type=adapter_event_type,
        source_event_id=source_event_id,
        source_participant_id=source_participant_id,
        target_participant_id=target_participant_id,
    )
    identity_token = _adapter_event_identity_token(
        event,
        adapter_event_type=adapter_event_type,
        source_event_id=source_event_id,
        payload=payload,
    )
    correlation_id = (
        _clean_optional(_value(event, "correlation_id", "workflow_id", "run_id"))
        or source_event_id
        or f"{run.run_id}:maf:{adapter_event_type}:{identity_token}"
    )
    idempotency_key = (
        _clean_optional(_value(event, "idempotency_key"))
        or f"{run.run_id}:maf:{adapter_event_type}:{source_event_id or identity_token}"
    )
    record = InterAgentEventRecord(
        event_id=context.event_id_for(f"{adapter_event_type}-{identity_token}"),
        workspace_id=run.workspace_id,
        run_id=run.run_id,
        thread_id=run.thread_id,
        root_runtime_session_id=run.root_runtime_session_id,
        participant_id=participant_id,
        runtime_session_id=None,
        runtime_turn_id=None,
        runtime_event_id=None,
        event_type=event_type,
        visibility_plane=visibility_plane,
        sequence=context.sequence_start + mapped_index,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        payload=payload,
        created_at=_created_at(context, event),
    )
    return validate_event_record(record)

def _safe_handoff_payload(
    event: object,
    *,
    adapter_event_type: str,
    source_event_id: str | None,
    source_participant_id: str | None,
    target_participant_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "adapter": "maf",
        "adapter_event_type": adapter_event_type,
    }
    if source_event_id:
        payload["source_event_id"] = source_event_id
    if source_participant_id:
        payload["source_participant_id"] = source_participant_id
    if target_participant_id:
        payload["target_participant_id"] = target_participant_id
    summary = _clean_optional(_value(event, "summary", "message", "content", "reason", "description"))
    if summary:
        payload["summary"] = summary
    task_id = _clean_optional(_value(event, "task_id", "conversation_id"))
    if task_id:
        payload["task_id"] = task_id
    return payload

def _handoff_correlation_id(
    source_participant_id: str | None,
    target_participant_id: str,
) -> str:
    source = source_participant_id or "unknown"
    return f"maf-handoff:{source}:{target_participant_id}"
