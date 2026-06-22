"""Magentic manager event projection for the MAF adapter."""

from __future__ import annotations

from typing import Any

from core.inter_agent.adapters.base import AdapterEventMappingContext
from core.inter_agent.adapters.group_chat import _group_chat_adapter_event_type
from core.inter_agent.adapters.shared import (
    _adapter_event_identity_token,
    _clean_optional,
    _created_at,
    _normalize_event_type,
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


_MAGENTIC_MANAGER_EXECUTOR_ID = "magentic_orchestrator"


def magentic_records(
    context: AdapterEventMappingContext,
    event: object,
    *,
    adapter_event_type: str,
    visibility_plane: InterAgentVisibilityPlane,
    source_index: int,
    mapped_index_start: int,
) -> list[InterAgentEventRecord]:
    magentic_event_type = _magentic_adapter_event_type(event, adapter_event_type)
    if magentic_event_type == "magentic_plan_created":
        return [
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.plan.summary_created",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="plan_summary",
            )
        ]
    if magentic_event_type == "magentic_replanned":
        return [
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.plan.summary_created",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="replan_summary",
            )
        ]
    if magentic_event_type == "magentic_progress_updated":
        return [
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.summary.updated",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="progress_observation",
            )
        ]
    if magentic_event_type == "group_chat_request_sent":
        return [
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.task.started",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="participant_dispatch",
            )
        ]
    if magentic_event_type == "group_chat_response_received":
        return [
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.task.completed",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="participant_response",
            )
        ]
    if magentic_event_type == "intermediate":
        participant_id = _clean_optional(_value(event, "executor_id", "participant_id"))
        summary = _safe_output_summary(event)
        if not participant_id or participant_id == _MAGENTIC_MANAGER_EXECUTOR_ID or not summary:
            return []
        return [
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.message.sent",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="participant_output",
            )
        ]
    if magentic_event_type == "output":
        summary = _safe_output_summary(event)
        if not summary:
            return []
        if _is_magentic_budget_exhaustion(summary):
            return [
                _magentic_record(
                    context,
                    event,
                    adapter_event_type=magentic_event_type,
                    event_type="inter_agent.budget.exceeded",
                    visibility_plane=visibility_plane,
                    source_index=source_index,
                    mapped_index=mapped_index_start,
                    payload_kind="budget_exhausted",
                ),
                _magentic_record(
                    context,
                    event,
                    adapter_event_type=magentic_event_type,
                    event_type="inter_agent.run.failed",
                    visibility_plane=visibility_plane,
                    source_index=source_index,
                    mapped_index=mapped_index_start + 1,
                    payload_kind="terminal_failure",
                ),
            ]
        if _clean_optional(_value(event, "executor_id")) not in {None, _MAGENTIC_MANAGER_EXECUTOR_ID}:
            return [
                _magentic_record(
                    context,
                    event,
                    adapter_event_type=magentic_event_type,
                    event_type="inter_agent.message.sent",
                    visibility_plane=visibility_plane,
                    source_index=source_index,
                    mapped_index=mapped_index_start,
                    payload_kind="participant_output",
                )
            ]
        return [
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.summary.updated",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="terminal_output",
            ),
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.run.completed",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start + 1,
                payload_kind="terminal_output",
            ),
        ]
    if magentic_event_type == "magentic_cancelled":
        return [
            _magentic_record(
                context,
                event,
                adapter_event_type=magentic_event_type,
                event_type="inter_agent.run.cancelled",
                visibility_plane=visibility_plane,
                source_index=source_index,
                mapped_index=mapped_index_start,
                payload_kind="terminal_cancelled",
            )
        ]
    return []

def _magentic_record(
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
    source_event_id = _magentic_source_event_id(event, adapter_event_type, source_index)
    payload = _safe_magentic_payload(
        context,
        event,
        adapter_event_type=adapter_event_type,
        source_event_id=source_event_id,
        payload_kind=payload_kind,
    )
    participant_id = _magentic_participant_id(context, event, event_type=event_type, payload=payload)
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
                "magentic",
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

def _safe_magentic_payload(
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
    content = _value(data, "content")
    participant_id = _clean_optional(_value(event, "executor_id", "participant_id", "participant_name"))
    if participant_id == _MAGENTIC_MANAGER_EXECUTOR_ID:
        participant_id = None
    selected_participant_id = _magentic_selected_participant_id(event)
    round_index = _clean_optional(_value(event, "round_index")) or _clean_optional(_value(data, "round_index"))
    summary = _magentic_summary(event, payload_kind=payload_kind)

    if participant_id and participant_id != context.run.orchestrator_participant_id:
        payload["participant_id"] = participant_id
    if selected_participant_id:
        payload["selected_participant_id"] = selected_participant_id
    if round_index:
        payload["round_index"] = round_index
    if payload_kind == "progress_observation":
        _add_magentic_progress_fields(payload, content)
    if summary:
        payload["summary"] = summary[:500]
    if payload_kind == "budget_exhausted":
        payload["budget_limit"] = _magentic_budget_limit(summary or "")
    if payload_kind.startswith("terminal"):
        payload["terminal_status"] = _terminal_status_for_payload_kind(payload_kind)
    return payload

def _magentic_adapter_event_type(event: object, adapter_event_type: str) -> str:
    if adapter_event_type == "magentic_orchestrator":
        data = _value(event, "data")
        event_type = _clean_optional(_value(data, "event_type"))
        if event_type:
            normalized = _normalize_event_type(event_type)
            if normalized == "progress_ledger_updated":
                normalized = "progress_updated"
            return f"magentic_{normalized}"
    return _group_chat_adapter_event_type(event, adapter_event_type)

def _magentic_source_event_id(event: object, adapter_event_type: str, source_index: int) -> str:
    explicit = _clean_optional(_value(event, "source_event_id", "event_id", "id", "request_id"))
    if explicit:
        return explicit
    data = _value(event, "data")
    round_index = _clean_optional(_value(event, "round_index")) or _clean_optional(_value(data, "round_index"))
    participant_id = _magentic_selected_participant_id(event) or _clean_optional(_value(event, "executor_id"))
    if participant_id == _MAGENTIC_MANAGER_EXECUTOR_ID:
        participant_id = None
    return ":".join(
        part
        for part in (
            "maf-magentic",
            str(source_index),
            adapter_event_type,
            round_index or "terminal",
            participant_id or "manager",
        )
        if part
    )

def _magentic_participant_id(
    context: AdapterEventMappingContext,
    event: object,
    *,
    event_type: InterAgentEventType,
    payload: dict[str, Any],
) -> str | None:
    if event_type in {
        "inter_agent.plan.summary_created",
        "inter_agent.summary.updated",
        "inter_agent.budget.exceeded",
        "inter_agent.run.completed",
        "inter_agent.run.failed",
    }:
        return context.run.orchestrator_participant_id
    if event_type == "inter_agent.run.cancelled":
        return _clean_optional(_value(event, "participant_id", "executor_id")) or context.run.orchestrator_participant_id
    return (
        _clean_optional(payload.get("participant_id"))
        or _clean_optional(payload.get("selected_participant_id"))
        or _clean_optional(_value(event, "executor_id", "participant_id", "participant_name"))
    )

def _is_magentic_budget_exhaustion(summary: str) -> bool:
    normalized = summary.strip().lower()
    return (
        "maximum round count" in normalized
        or "maximum reset count" in normalized
        or "max_round_count" in normalized
        or "max_reset_count" in normalized
    )

def _magentic_budget_limit(summary: str) -> str:
    normalized = summary.strip().lower()
    if "reset" in normalized:
        return "max_resets"
    return "max_rounds"

def _magentic_summary(event: object, *, payload_kind: str) -> str | None:
    if payload_kind == "progress_observation":
        return _magentic_progress_summary(_value(_value(event, "data"), "content"))
    if payload_kind in {"plan_summary", "replan_summary"}:
        return _safe_message_text(_value(_value(event, "data"), "content"))
    return _safe_output_summary(event) or _clean_optional(
        _value(event, "summary", "message", "content", "reason", "description")
    )

def _magentic_progress_summary(content: object) -> str:
    request_status = "satisfied" if _magentic_progress_answer_bool(content, "is_request_satisfied") else "open"
    progress_status = (
        "moving" if _magentic_progress_answer_bool(content, "is_progress_being_made") else "stalled"
    )
    loop_status = "loop_detected" if _magentic_progress_answer_bool(content, "is_in_loop") else "not_looping"
    next_speaker = _clean_optional(_magentic_progress_answer(content, "next_speaker"))
    parts = [f"request {request_status}", f"progress {progress_status}", loop_status]
    if next_speaker:
        parts.append(f"next speaker {next_speaker}")
    return "Magentic progress: " + "; ".join(parts) + "."

def _add_magentic_progress_fields(payload: dict[str, Any], content: object) -> None:
    request_satisfied = _magentic_progress_answer_bool(content, "is_request_satisfied")
    in_loop = _magentic_progress_answer_bool(content, "is_in_loop")
    progress_made = _magentic_progress_answer_bool(content, "is_progress_being_made")
    payload["request_status"] = "satisfied" if request_satisfied else "open"
    payload["progress_status"] = "moving" if progress_made else "stalled"
    payload["loop_status"] = "loop_detected" if in_loop else "not_looping"
    payload["stall_detected"] = "true" if in_loop or not progress_made else "false"

def _magentic_progress_answer_bool(content: object, item_name: str) -> bool:
    value = _magentic_progress_answer(content, item_name)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"

def _magentic_progress_answer(content: object, item_name: str) -> object:
    item = _value(content, item_name)
    return _value(item, "answer")

def _magentic_selected_participant_id(event: object) -> str | None:
    data = _value(event, "data")
    content = _value(data, "content")
    selected = (
        _clean_optional(_value(event, "selected_participant_id", "next_speaker", "participant_id", "participant_name"))
        or _clean_optional(_value(data, "participant_name", "selected_participant_id", "next_speaker"))
        or _clean_optional(_magentic_progress_answer(content, "next_speaker"))
    )
    if selected == _MAGENTIC_MANAGER_EXECUTOR_ID:
        return None
    return selected

def _safe_message_text(message: object) -> str | None:
    text = _clean_optional(_value(message, "text"))
    if text:
        return text[:500]
    contents = _value(message, "contents")
    if isinstance(contents, (list, tuple)):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
                continue
            item_text = _clean_optional(_value(item, "text"))
            if item_text:
                parts.append(item_text)
        if parts:
            return " ".join(parts)[:500]
    return None
