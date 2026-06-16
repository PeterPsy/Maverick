"""Stateful Codex app-server protocol client."""

from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path
import queue
from typing import Any

from core.observability.service import append_platform_log
from core.runtime.execution_events import (
    RuntimeExecutionEvent,
    is_non_chat_facing_provider_event,
    parse_provider_json_event,
)


def _emit_structured_output(
    runtime: _CodexAppServerRuntime,
    *,
    provider_event_type: str,
    structured: dict[str, Any],
    tool_call_id: str | None,
) -> None:
    key = json.dumps(structured, sort_keys=True, separators=(",", ":"))
    with runtime.event_lock:
        if key in runtime.emitted_structured_keys:
            return
        runtime.emitted_structured_keys.add(key)
    _emit(
        runtime,
        RuntimeExecutionEvent(
            event_type="runtime.output.structured",
            payload={
                "structured_content": structured,
                "provider_event_type": provider_event_type,
                "tool_call_id": tool_call_id,
            },
        ),
    )



def _parse_structured_agent_output(value: str) -> dict[str, Any] | None:
    payload = _decode_json_object(value)
    if payload is None:
        return None
    structured = _structured_content_from_payload(payload)
    if structured is None:
        return None
    text = str(payload.get("text") or "").strip()
    return {"text": text, "structured_content": structured}



def _structured_content_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    structured_payload = payload.get("structured_content") or payload.get("structuredContent") or payload.get("content")
    if isinstance(structured_payload, dict):
        structured = _structured_content_record(structured_payload)
        if structured is not None:
            return structured
    chat_render = payload.get("chat_render")
    if isinstance(chat_render, dict):
        return _structured_content_record(chat_render)
    return None



def _structured_content_record(value: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(value.get("kind") or "").strip()
    if not kind:
        return None
    content_payload = value.get("payload") if isinstance(value.get("payload"), dict) else value
    return {"kind": kind, "payload": content_payload}



def _structured_content_from_completed_item(*, provider_type: str, item: dict[str, Any]) -> dict[str, Any] | None:
    if not provider_type.endswith("completed"):
        return None
    if str(item.get("type") or "").strip() != "commandExecution":
        return None
    output = str(item.get("aggregatedOutput") or item.get("aggregated_output") or item.get("stdout") or "").strip()
    if not output:
        return None
    payload = _decode_json_object(output)
    if payload is None:
        return None
    return _structured_content_from_payload(payload)



def _decode_json_object(value: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(value[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None



def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("itemId") or item.get("item_id") or "").strip()



def _handle_generic_notification(runtime: _CodexAppServerRuntime, *, method: str, params: dict[str, Any]) -> None:
    if is_non_chat_facing_provider_event(method):
        return
    provider_type = method.replace("/", ".")
    event = parse_provider_json_event(json.dumps({"type": provider_type, "item": params}))
    if event is not None:
        _emit(runtime, event)
        return
    _emit(runtime, RuntimeExecutionEvent(event_type="runtime.step.updated", payload={"label": provider_type.replace(".", " "), "provider_event_type": method, "raw": params}))



def _put_completion(runtime: _CodexAppServerRuntime, value: dict[str, Any]) -> None:
    with runtime.event_lock:
        runtime.current_completion_received = True
    try:
        runtime.completion_queue.put_nowait(value)
    except queue.Full:
        _debug_log(
            runtime,
            "Codex app-server debug: duplicate completion ignored",
            {
                "phase": "duplicate_completion_ignored",
                "provider_turn_id": runtime.current_provider_turn_id,
                "completion_status": str(value.get("status") or "").strip() or None,
                "process_pid": runtime.process.pid,
                "process_returncode": runtime.process.poll(),
            },
        )
        return



def _emit(runtime: _CodexAppServerRuntime, event: RuntimeExecutionEvent) -> None:
    with runtime.event_lock:
        sink = runtime.current_event_sink
    if sink is not None:
        sink(event)



def _debug_log(runtime: _CodexAppServerRuntime, message: str, payload: dict[str, Any]) -> None:
    """Write best-effort Codex protocol diagnostics without affecting turn execution."""
    with suppress(Exception):
        append_platform_log(
            log_plane="runtime",
            message=message,
            payload={
                "component": "codex_app_server",
                "session_id": runtime.session_id,
                **payload,
            },
            workspace_id=runtime.workspace_id,
            runtime_session_id=runtime.session_id,
            provider_id="codex",
            start_path=Path(runtime.runtime_root),
        )
