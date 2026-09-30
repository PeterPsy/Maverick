"""Stateful Codex app-server protocol client."""

from __future__ import annotations

import json
import time
from typing import Any

from core.providers.codex_app_server_runtime_errors import (
    codex_error_info,
    codex_terminal_failure_reason_code,
)
from core.providers.codex_agent_messages import (
    emit_agent_message_delta,
    flush_pending_agent_json_chunks as _flush_pending_agent_json_chunks,
    handle_agent_message_item,
    is_agent_message_item as _is_agent_message_item,
)
from core.providers.codex_app_server_skill_rehydration import schedule_codex_skill_rehydration
from core.providers.codex_app_server_runtime_usage import codex_usage_event as _codex_usage_event
from core.providers.codex_prompt_budget import final_prompt_budget_payload
from core.runtime.execution_events import RuntimeExecutionEvent, parse_provider_json_event


_CODEX_RESEARCH_ALLOWED_ITEM_TYPES = frozenset(
    {
        "agentMessage",
        "AgentMessage",
        "contextCompaction",
        "plan",
        "reasoning",
        "userMessage",
        "webSearch",
    }
)


def _handle_notification(runtime: _CodexAppServerRuntime, payload: dict[str, Any]) -> None:
    method = str(payload.get("method") or "")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    if method == "thread/tokenUsage/updated":
        usage_event = _codex_usage_event(runtime, params)
        if usage_event is not None:
            _emit(runtime, usage_event)
        return
    if method == "turn/started":
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        provider_turn_id = str(turn.get("id") or "").strip()
        if provider_turn_id:
            runtime.current_provider_turn_id = provider_turn_id
        _debug_log(
            runtime,
            "Codex app-server debug: turn/started notification",
            {
                "phase": "notification_turn_started",
                "provider_turn_id": runtime.current_provider_turn_id,
                "provider_status": str(turn.get("status") or "").strip() or None,
                "process_pid": runtime.process.pid,
                "process_returncode": runtime.process.poll(),
            },
        )
        return
    if method == "turn/completed":
        _flush_pending_agent_json_chunks(runtime, provider_event_type=method)
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        token_usage = turn.get("tokenUsage") if isinstance(turn.get("tokenUsage"), dict) else None
        if token_usage is not None:
            usage_event = _codex_usage_event(
                runtime,
                {
                    "threadId": runtime.provider_thread_id,
                    "turnId": turn.get("id") or runtime.current_provider_turn_id,
                    "tokenUsage": token_usage,
                },
                final_snapshot=True,
            )
            if usage_event is not None:
                _emit(runtime, usage_event)
        if getattr(runtime, "prompt_budget_pending", False):
            budget_payload = final_prompt_budget_payload(runtime)
            if budget_payload is not None:
                _emit(
                    runtime,
                    RuntimeExecutionEvent(
                        event_type="runtime.prompt_budget.evaluated",
                        payload=budget_payload,
                    ),
                )
            runtime.prompt_budget_pending = False
        _debug_log(
            runtime,
            "Codex app-server debug: turn/completed notification",
            {
                "phase": "notification_turn_completed",
                "provider_turn_id": runtime.current_provider_turn_id,
                "provider_status": str(turn.get("status") or "").strip() or None,
                "process_pid": runtime.process.pid,
                "process_returncode": runtime.process.poll(),
            },
        )
        _put_completion(runtime, {"status": str(turn.get("status") or "completed")})
        return
    if method == "item/agentMessage/delta":
        emit_agent_message_delta(runtime, params=params, provider_type=method)
        return
    if method in {"item/started", "item/completed"}:
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        if method == "item/completed" and _is_agent_message_item(item):
            _debug_log(
                runtime,
                "Codex app-server debug: agent message item completed",
                {
                    "phase": "agent_message_item_completed",
                    "provider_turn_id": runtime.current_provider_turn_id,
                    "item_id": _item_id(item) or None,
                    "item_status": str(item.get("status") or "").strip() or None,
                    "text_length": len(str(item.get("text") or "")),
                    "process_pid": runtime.process.pid,
                    "process_returncode": runtime.process.poll(),
                },
            )
        _handle_item_event(runtime, provider_type=method.replace("/", "."), item=item)
        if method == "item/completed" and _is_context_compaction_item(item):
            schedule_codex_skill_rehydration(runtime, compaction_item_id=_item_id(item))
        return
    if method == "error":
        error_text = _extract_error_text(params)
        will_retry = bool(params.get("willRetry"))
        error_info = codex_error_info(params)
        failure_reason_code = (
            None if will_retry else codex_terminal_failure_reason_code(error_info)
        )
        with runtime.event_lock:
            runtime.current_error_text = error_text
            if failure_reason_code is not None:
                runtime.current_failure_reason_code = failure_reason_code
                runtime.current_terminal_error_at = time.monotonic()
        _debug_log(
            runtime,
            "Codex app-server debug: error notification",
            {
                "phase": "notification_error",
                "provider_turn_id": runtime.current_provider_turn_id,
                "will_retry": will_retry,
                "codex_error_info": error_info,
                "failure_reason_code": failure_reason_code,
                "has_error_text": bool(error_text),
                "process_pid": runtime.process.pid,
                "process_returncode": runtime.process.poll(),
            },
        )
        if will_retry:
            _emit(
                runtime,
                RuntimeExecutionEvent(
                    event_type="runtime.step.updated",
                    payload={
                        "label": "Model provider retrying",
                        "will_retry": True,
                    },
                ),
            )
        return
    _handle_generic_notification(runtime, method=method, params=params)


def _extract_error_text(params: dict[str, Any]) -> str:
    error = params.get("error") if isinstance(params.get("error"), dict) else {}
    details = str(error.get("additionalDetails") or "").strip()
    message = str(error.get("message") or "").strip()
    if details:
        return details
    if message:
        return message
    return "Codex app-server failed."


def _handle_item_event(runtime: _CodexAppServerRuntime, *, provider_type: str, item: dict[str, Any]) -> None:
    item_type = str(item.get("type") or "").strip()
    if (
        getattr(runtime, "research", False)
        and item_type not in _CODEX_RESEARCH_ALLOWED_ITEM_TYPES
    ):
        _fail_research_item(runtime, item_type=item_type)
        return
    if _is_agent_message_item(item):
        handle_agent_message_item(runtime, provider_type=provider_type, item=item)
        return
    event = parse_provider_json_event(json.dumps({"type": provider_type, "item": item}))
    if event is not None and not _research_event_allowed(runtime, event):
        _fail_research_item(runtime, item_type=item_type)
        return
    if event is not None:
        _emit(runtime, event)
    structured = _structured_content_from_completed_item(provider_type=provider_type, item=item)
    if structured is not None:
        _emit_structured_output(
            runtime,
            provider_event_type=provider_type,
            structured=structured,
            tool_call_id=_item_id(item) or None,
        )


def _fail_research_item(runtime: _CodexAppServerRuntime, *, item_type: str) -> None:
    label = item_type or "unknown"
    with runtime.event_lock:
        runtime.current_error_text = (
            f"Codex exposed disallowed Research item `{label}`."
        )
        runtime.current_failure_reason_code = "research_runtime_unavailable"
        runtime.current_terminal_error_at = time.monotonic()
    _put_completion(runtime, {"status": "failed"})
    try:
        runtime.process.terminate()
    except OSError:
        pass


def _research_event_allowed(
    runtime: _CodexAppServerRuntime,
    event: RuntimeExecutionEvent,
) -> bool:
    if not getattr(runtime, "research", False):
        return True
    if not event.event_type.startswith("runtime.tool_call."):
        return True
    return event.payload.get("tool_kind") == "web_search"


def _is_context_compaction_item(item: dict[str, Any]) -> bool:
    return str(item.get("type") or "").strip() in {"contextCompaction", "context_compaction"}
