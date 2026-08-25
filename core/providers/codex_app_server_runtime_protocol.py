"""Stateful Codex app-server protocol client."""

from __future__ import annotations

import json
from typing import Any

from core.providers.codex_app_server_skill_rehydration import schedule_codex_skill_rehydration
from core.providers.codex_app_server_runtime_usage import codex_usage_event as _codex_usage_event
from core.providers.codex_prompt_budget import final_prompt_budget_payload
from core.runtime.execution_events import RuntimeExecutionEvent, parse_provider_json_event


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
        delta = str(params.get("delta") or "")
        if delta:
            item_id = _item_id(params)
            if item_id and _should_buffer_agent_json_delta(runtime=runtime, item_id=item_id, delta=delta):
                return
            with runtime.event_lock:
                runtime.current_chunks.append(delta)
                if item_id:
                    runtime.streamed_agent_item_ids.add(item_id)
            _emit(runtime, RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": delta, "provider_event_type": method}))
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
        with runtime.event_lock:
            runtime.current_error_text = error_text
        _debug_log(
            runtime,
            "Codex app-server debug: error notification",
            {
                "phase": "notification_error",
                "provider_turn_id": runtime.current_provider_turn_id,
                "will_retry": bool(params.get("willRetry")),
                "has_error_text": bool(error_text),
                "process_pid": runtime.process.pid,
                "process_returncode": runtime.process.poll(),
            },
        )
        _emit(runtime, RuntimeExecutionEvent(event_type="runtime.step.updated", payload={"label": "Codex app-server error", "raw": params}))
        if not bool(params.get("willRetry")):
            _put_completion(runtime, {"status": "failed"})
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
    if _is_agent_message_item(item) and provider_type.endswith("completed"):
        if _emit_completed_agent_message_output(runtime=runtime, provider_type=provider_type, item=item):
            return
        text = str(item.get("text") or "").strip()
        if text:
            item_id = _item_id(item)
            with runtime.event_lock:
                already_streamed = item_id in runtime.streamed_agent_item_ids if item_id else bool(runtime.current_chunks)
                if not already_streamed:
                    runtime.current_chunks.append(text)
            if not already_streamed:
                _emit(runtime, RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": text, "provider_event_type": provider_type}))
            return
    event = parse_provider_json_event(json.dumps({"type": provider_type, "item": item}))
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


def _is_agent_message_item(item: dict[str, Any]) -> bool:
    return str(item.get("type") or "").strip() in {"agentMessage", "agent_message"}


def _is_context_compaction_item(item: dict[str, Any]) -> bool:
    return str(item.get("type") or "").strip() in {"contextCompaction", "context_compaction"}


def _should_buffer_agent_json_delta(*, runtime: _CodexAppServerRuntime, item_id: str, delta: str) -> bool:
    with runtime.event_lock:
        pending = runtime.pending_agent_json_chunks.get(item_id)
        if pending is not None:
            pending.append(delta)
            return True
        if delta.lstrip().startswith("{"):
            runtime.pending_agent_json_chunks[item_id] = [delta]
            return True
    return False


def _emit_completed_agent_message_output(*, runtime: _CodexAppServerRuntime, provider_type: str, item: dict[str, Any]) -> bool:
    item_id = _item_id(item)
    text = str(item.get("text") or "")
    pending_text = _pop_pending_agent_json_chunk(runtime, item_id)
    candidate_text = text or pending_text
    if candidate_text:
        parsed = _parse_structured_agent_output(candidate_text)
        if parsed is not None:
            _emit_agent_text_output(runtime=runtime, provider_event_type=provider_type, item_id=item_id, text=parsed.get("text") or "")
            _emit_structured_output(
                runtime,
                provider_event_type=provider_type,
                structured=parsed["structured_content"],
                tool_call_id=item_id or None,
            )
            return True
    if pending_text:
        _emit_agent_text_output(runtime=runtime, provider_event_type=provider_type, item_id=item_id, text=candidate_text)
        return True
    return False


def _pop_pending_agent_json_chunk(runtime: _CodexAppServerRuntime, item_id: str) -> str:
    if not item_id:
        return ""
    with runtime.event_lock:
        chunks = runtime.pending_agent_json_chunks.pop(item_id, None)
    return "".join(chunks or [])


def _emit_agent_text_output(*, runtime: _CodexAppServerRuntime, provider_event_type: str, item_id: str, text: str) -> None:
    if not text:
        return
    with runtime.event_lock:
        runtime.current_chunks.append(text)
        if item_id:
            runtime.streamed_agent_item_ids.add(item_id)
    _emit(runtime, RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": text, "provider_event_type": provider_event_type}))


def _flush_pending_agent_json_chunks(runtime: _CodexAppServerRuntime, *, provider_event_type: str) -> None:
    with runtime.event_lock:
        pending_items = list(runtime.pending_agent_json_chunks.items())
        runtime.pending_agent_json_chunks = {}
    for item_id, chunks in pending_items:
        text = "".join(chunks)
        if not text:
            continue
        parsed = _parse_structured_agent_output(text)
        if parsed is not None:
            _emit_agent_text_output(runtime=runtime, provider_event_type=provider_event_type, item_id=item_id, text=parsed.get("text") or "")
            _emit_structured_output(
                runtime,
                provider_event_type=provider_event_type,
                structured=parsed["structured_content"],
                tool_call_id=item_id or None,
            )
            continue
        _emit_agent_text_output(runtime=runtime, provider_event_type=provider_event_type, item_id=item_id, text=text)
