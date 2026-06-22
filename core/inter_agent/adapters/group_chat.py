"""Group-chat event projection for the MAF adapter."""

from __future__ import annotations

from typing import Any

from core.inter_agent.adapters.base import AdapterEventMappingContext
from core.inter_agent.adapters.shared import (
    _adapter_event_identity_token,
    _clean_optional,
    _created_at,
    _safe_output_summary,
    _terminal_status_for_payload_kind,
    _value,
)
from core.inter_agent.events import (
    InterAgentEventRecord,
    InterAgentEventType,
    InterAgentVisibilityPlane,
    validate_event_record,
)


_GROUP_CHAT_MANAGER_DECISION_EVENT_TYPES = {
    "group_chat_manager_decision",
    "manager_decision",
}
_GROUP_CHAT_SPEAKER_SELECTION_EVENT_TYPES = {
    "group_chat_speaker_selection",
    "speaker_selection",
}
_GROUP_CHAT_TERMINAL_FAILURE_TYPES = {
    "group_chat_budget_exceeded",
    "group_chat_failed",
}

def group_chat_records(
    context: AdapterEventMappingContext,
    event: object,
    *,
    adapter_event_type: str,
    visibility_plane: InterAgentVisibilityPlane,
    source_index: int,
    mapped_index_start: int,
) -> list[InterAgentEventRecord]:
    group_chat_event_type = _group_chat_adapter_event_type(event, adapter_event_type)
    if group_chat_event_type == "group_chat_request_sent":
        return [
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.task.started",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="speaker_selection",
            )
        ]
    if group_chat_event_type == "group_chat_response_received":
        return [
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.task.completed",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="participant_response",
            )
        ]
    if group_chat_event_type == "intermediate":
        participant_id = _clean_optional(_value(event, "executor_id", "participant_id"))
        summary = _safe_output_summary(event)
        if not participant_id or not summary:
            return []
        return [
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.message.sent",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="participant_output",
            )
        ]
    if group_chat_event_type == "output":
        summary = _safe_output_summary(event)
        if not summary:
            return []
        if _is_group_chat_budget_exhaustion(summary):
            return [
                _group_chat_record(
                    context,
                    event,
                    adapter_event_type=group_chat_event_type,
                    event_type="inter_agent.budget.exceeded",
                    visibility_plane=visibility_plane,
                    source_index=source_index,
                    mapped_index=mapped_index_start,
                    payload_kind="budget_exhausted",
                ),
                _group_chat_record(
                    context,
                    event,
                    adapter_event_type=group_chat_event_type,
                    event_type="inter_agent.run.failed",
                    visibility_plane=visibility_plane,
                    source_index=source_index,
                    mapped_index=mapped_index_start + 1,
                    payload_kind="terminal_failure",
                ),
            ]
        return [
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.summary.updated",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="terminal_output",
            ),
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.run.completed",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start + 1,
                payload_kind="terminal_output",
            ),
        ]
    if group_chat_event_type in _GROUP_CHAT_SPEAKER_SELECTION_EVENT_TYPES:
        selected_participant_id = _clean_optional(
            _value(event, "selected_participant_id", "participant_id", "participant_name", "next_speaker")
        )
        if not selected_participant_id:
            return []
        return [
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.summary.updated",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="speaker_selection",
            )
        ]
    if group_chat_event_type in _GROUP_CHAT_MANAGER_DECISION_EVENT_TYPES:
        selected_participant_id = _clean_optional(
            _value(event, "selected_participant_id", "participant_id", "participant_name", "next_speaker")
        )
        if not selected_participant_id:
            return []
        return [
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.summary.updated",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="manager_decision",
            )
        ]
    if group_chat_event_type in _GROUP_CHAT_TERMINAL_FAILURE_TYPES:
        return [
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.budget.exceeded"
                if group_chat_event_type == "group_chat_budget_exceeded"
                else "inter_agent.run.failed",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="budget_exhausted"
                if group_chat_event_type == "group_chat_budget_exceeded"
                else "terminal_failure",
            )
        ]
    if group_chat_event_type == "group_chat_cancelled":
        return [
            _group_chat_record(
                context,
                event,
                adapter_event_type=group_chat_event_type,
                event_type="inter_agent.run.cancelled",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="terminal_cancelled",
            )
        ]
    return []

def _group_chat_record(
    context: AdapterEventMappingContext,
    event: object,
    *,
    adapter_event_type: str,
    event_type: InterAgentEventType,
    visibility_plane: InterAgentVisibilityPlane,
    source_index: int,
    mapped_index: int,
    payload_kind: str,
) -> InterAgentEventRecord:
    run = context.run
    source_event_id = _group_chat_source_event_id(event, adapter_event_type, source_index)
    payload = _safe_group_chat_payload(
        context,
        event,
        adapter_event_type=adapter_event_type,
        source_event_id=source_event_id,
        payload_kind=payload_kind,
    )
    participant_id = _group_chat_participant_id(
        context,
        event,
        event_type=event_type,
        payload=payload,
    )
    identity_token = _adapter_event_identity_token(
        event,
        adapter_event_type=f"{adapter_event_type}:{event_type}",
        source_event_id=source_event_id,
        payload=payload,
    )
    round_index = payload.get("round_index")
    selected_participant_id = payload.get("selected_participant_id")
    correlation_id = (
        _clean_optional(_value(event, "correlation_id", "workflow_id", "run_id"))
        or ":".join(
            str(part)
            for part in (
                run.run_id,
                "maf",
                "group_chat",
                round_index or "terminal",
                selected_participant_id or participant_id or payload_kind,
            )
            if part
        )
    )
    explicit_idempotency_key = _clean_optional(_value(event, "idempotency_key"))
    idempotency_key = (
        f"{run.run_id}:maf:{adapter_event_type}:{event_type}:{explicit_idempotency_key}"
        if explicit_idempotency_key
        else f"{run.run_id}:maf:{adapter_event_type}:{event_type}:{source_event_id or identity_token}"
    )
    record = InterAgentEventRecord(
        event_id=context.event_id_for(f"{adapter_event_type}-{event_type.split('.')[-1]}-{identity_token}"),
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

def _safe_group_chat_payload(
    context: AdapterEventMappingContext,
    event: object,
    *,
    adapter_event_type: str,
    source_event_id: str | None,
    payload_kind: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "adapter": "maf",
        "adapter_event_type": adapter_event_type,
        "observation_kind": payload_kind,
    }
    if source_event_id:
        payload["source_event_id"] = source_event_id
    data = _value(event, "data")
    participant_id = _clean_optional(_value(event, "executor_id", "participant_id", "participant_name"))
    selected_participant_id = _clean_optional(
        _value(
            event,
            "selected_participant_id",
            "next_speaker",
            "participant_name",
            "target_participant_id",
        )
    ) or _clean_optional(_value(data, "participant_name", "selected_participant_id", "next_speaker"))
    round_index = _clean_optional(_value(event, "round_index")) or _clean_optional(_value(data, "round_index"))
    summary = _safe_output_summary(event) or _clean_optional(
        _value(event, "summary", "reason", "message", "content", "description")
    )
    decision_source = _clean_optional(_value(event, "decision_source", "source"))

    if (
        participant_id
        and participant_id != context.run.orchestrator_participant_id
        and not payload_kind.startswith("terminal")
        and payload_kind != "budget_exhausted"
    ):
        payload["participant_id"] = participant_id
    if selected_participant_id:
        payload["selected_participant_id"] = selected_participant_id
    if round_index:
        payload["round_index"] = round_index
    if decision_source:
        payload["decision_source"] = decision_source
    elif payload_kind == "speaker_selection":
        payload["decision_source"] = "maf_group_chat"
    elif payload_kind == "manager_decision":
        payload["decision_source"] = "manager_agent"
    if summary:
        payload["summary"] = summary[:500]
    if payload_kind == "budget_exhausted":
        payload["budget_limit"] = "max_rounds"
    if payload_kind.startswith("terminal"):
        payload["terminal_status"] = _terminal_status_for_payload_kind(payload_kind)
    return payload

def _group_chat_adapter_event_type(event: object, adapter_event_type: str) -> str:
    if adapter_event_type != "group_chat":
        return adapter_event_type
    data = _value(event, "data")
    data_type = type(data).__name__ if data is not None else ""
    if data_type == "GroupChatRequestSentEvent":
        return "group_chat_request_sent"
    if data_type == "GroupChatResponseReceivedEvent":
        return "group_chat_response_received"
    return adapter_event_type

def _group_chat_source_event_id(event: object, adapter_event_type: str, source_index: int) -> str:
    explicit = _clean_optional(_value(event, "source_event_id", "event_id", "id"))
    if explicit:
        return explicit
    data = _value(event, "data")
    round_index = _clean_optional(_value(event, "round_index")) or _clean_optional(_value(data, "round_index"))
    participant_id = (
        _clean_optional(_value(event, "selected_participant_id", "next_speaker", "participant_id", "participant_name"))
        or _clean_optional(_value(data, "participant_name", "selected_participant_id", "next_speaker"))
        or _clean_optional(_value(event, "executor_id"))
    )
    if participant_id == "group_chat_orchestrator":
        participant_id = None
    return ":".join(
        part
        for part in (
            "maf-group-chat",
            str(source_index),
            adapter_event_type,
            round_index or "terminal",
            participant_id or "workflow",
        )
        if part
    )

def _group_chat_participant_id(
    context: AdapterEventMappingContext,
    event: object,
    *,
    event_type: InterAgentEventType,
    payload: dict[str, Any],
) -> str | None:
    if event_type in {"inter_agent.summary.updated", "inter_agent.run.completed", "inter_agent.run.failed"}:
        return context.run.orchestrator_participant_id
    if event_type == "inter_agent.budget.exceeded":
        return context.run.orchestrator_participant_id
    if event_type == "inter_agent.run.cancelled":
        return _clean_optional(_value(event, "participant_id", "executor_id")) or context.run.orchestrator_participant_id
    return (
        _clean_optional(payload.get("participant_id"))
        or _clean_optional(payload.get("selected_participant_id"))
        or _clean_optional(_value(event, "executor_id", "participant_id", "participant_name"))
    )

def _is_group_chat_budget_exhaustion(summary: str) -> bool:
    normalized = summary.strip().lower()
    return "maximum number of rounds" in normalized or "max_round" in normalized or "max rounds" in normalized
