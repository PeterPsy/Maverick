"""Codex message identity, phases, and once-only text delivery."""

from __future__ import annotations

from typing import Any

from core.providers.codex_app_server_runtime_notifications import (
    _emit,
    _emit_structured_output,
    _item_id,
    _parse_structured_agent_output,
)
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime
from core.runtime.execution_events import RuntimeExecutionEvent


def is_agent_message_item(item: dict[str, Any]) -> bool:
    return str(item.get("type") or "").strip() in {"agentMessage", "agent_message", "AgentMessage"}


def _message_text(item: dict[str, Any]) -> str:
    if isinstance(item.get("text"), str):
        return item["text"]
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part["text"] for part in content if isinstance(part, dict)
            and part.get("type") in {"Text", "text", "output_text"}
            and isinstance(part.get("text"), str)
        )
    return ""


def _message_phase(item: dict[str, Any]) -> str | None:
    if item.get("delivery") == "async" or item.get("questions"):
        return "commentary"
    phase = str(item.get("phase") or "")
    if phase in {"final_answer", "final"}:
        return "final"
    return "commentary" if phase == "commentary" else None


def _emit_text(runtime: _CodexAppServerRuntime, *, provider_type: str, item_id: str, text: str) -> None:
    if not text:
        return
    with runtime.event_lock:
        runtime.current_chunks.append(text)
        if item_id:
            runtime.streamed_agent_item_ids.add(item_id)
        phase = runtime.agent_message_phases.get(item_id)
    _emit(runtime, RuntimeExecutionEvent(event_type="runtime.output.delta", payload={
        "text": text, "provider_event_type": provider_type,
        **({"message_id": item_id} if item_id else {}),
        **({"phase": phase} if phase else {}),
    }))


def emit_agent_message_delta(runtime: _CodexAppServerRuntime, *, params: dict, provider_type: str) -> None:
    delta = str(params.get("delta") or "")
    if not delta:
        return
    item_id = _item_id(params)
    with runtime.event_lock:
        pending = runtime.pending_agent_json_chunks.get(item_id)
        if item_id and (pending is not None or delta.lstrip().startswith("{")):
            runtime.pending_agent_json_chunks.setdefault(item_id, []).append(delta)
            return
    _emit_text(runtime, provider_type=provider_type, item_id=item_id, text=delta)


def handle_agent_message_item(runtime: _CodexAppServerRuntime, *, provider_type: str, item: dict) -> None:
    item_id = _item_id(item)
    phase = _message_phase(item)
    with runtime.event_lock:
        if phase and item_id:
            runtime.agent_message_phases[item_id] = phase
    if not provider_type.endswith("completed"):
        return
    with runtime.event_lock:
        pending = "".join(runtime.pending_agent_json_chunks.pop(item_id, []))
        already_streamed = item_id in runtime.streamed_agent_item_ids if item_id else bool(runtime.current_chunks)
    text = _message_text(item) or pending
    parsed = _parse_structured_agent_output(text) if text else None
    visible_text = parsed["text"] if parsed else text
    if pending or not already_streamed:
        _emit_text(runtime, provider_type=provider_type, item_id=item_id, text=visible_text)
    if parsed:
        _emit_structured_output(runtime, provider_event_type=provider_type,
                               structured=parsed["structured_content"], tool_call_id=item_id or None)
    with runtime.event_lock:
        resolved_phase = phase or runtime.agent_message_phases.get(item_id)
        if resolved_phase == "final" and visible_text:
            runtime.current_final_answer = visible_text
    _emit(runtime, RuntimeExecutionEvent(event_type="runtime.output.message.completed", payload={
        "provider_event_type": provider_type,
        **({"message_id": item_id} if item_id else {}),
        **({"phase": resolved_phase} if resolved_phase else {}),
    }))


def flush_pending_agent_json_chunks(runtime: _CodexAppServerRuntime, *, provider_event_type: str) -> None:
    with runtime.event_lock:
        pending_items = list(runtime.pending_agent_json_chunks.items())
        runtime.pending_agent_json_chunks = {}
    for item_id, chunks in pending_items:
        text = "".join(chunks)
        if not text:
            continue
        parsed = _parse_structured_agent_output(text)
        _emit_text(runtime, provider_type=provider_event_type, item_id=item_id,
                   text=parsed["text"] if parsed else text)
        if parsed:
            _emit_structured_output(runtime, provider_event_type=provider_event_type,
                                   structured=parsed["structured_content"], tool_call_id=item_id or None)
