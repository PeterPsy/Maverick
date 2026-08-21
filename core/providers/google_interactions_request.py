"""Translate provider-neutral agentic requests into Google Interactions input."""

from __future__ import annotations

import json

from core.providers.agentic_protocol import AgenticModelRequest, AgenticToolResult
from core.providers.google_interactions_models import (
    GoogleInteractionState,
    GoogleInteractionsProtocolError,
)


def google_interaction_payload(
    request: AgenticModelRequest,
    state: GoogleInteractionState,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    """Return the exact wire payload and new input steps used for history."""
    new_input = _new_input_steps(request, state)
    interaction_input = [*state.history, *new_input] if state.mode == "stateless" else list(new_input)
    if not interaction_input:
        raise GoogleInteractionsProtocolError("provider_request_invalid")
    payload: dict[str, object] = {
        "model": request.model_id,
        "input": interaction_input,
        "tools": [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }
            for tool in request.tool_definitions
        ],
        "stream": True,
        "store": state.mode == "stateful",
        "generation_config": {
            "max_output_tokens": request.max_output_tokens,
            "thinking_summaries": "none",
            **_thinking_level(request.reasoning_effort),
        },
    }
    system_instruction = _system_instruction(request)
    if system_instruction:
        payload["system_instruction"] = system_instruction
    if state.mode == "stateful" and state.previous_interaction_id:
        payload["previous_interaction_id"] = state.previous_interaction_id
    return payload, new_input


def _new_input_steps(
    request: AgenticModelRequest,
    state: GoogleInteractionState,
) -> tuple[dict[str, object], ...]:
    if state.pending_function_calls:
        return tuple(_function_results(request.tool_results, state))
    if (
        set(_tool_results_by_id(request.tool_results))
        - set(state.consumed_function_call_ids)
    ):
        raise GoogleInteractionsProtocolError("provider_tool_result_pairing_invalid")
    content = []
    for block in request.content_blocks:
        if block.role == "system":
            continue
        if block.role != "user" or not block.content_type.startswith("text/"):
            raise GoogleInteractionsProtocolError("provider_request_invalid")
        content.append({"type": "text", "text": _decode_utf8(block.content)})
    if not content:
        raise GoogleInteractionsProtocolError("provider_request_invalid")
    return ({"type": "user_input", "content": content},)


def _function_results(
    results: tuple[AgenticToolResult, ...],
    state: GoogleInteractionState,
) -> list[dict[str, object]]:
    by_id = _tool_results_by_id(results)
    pending_ids = {item.call_id for item in state.pending_function_calls}
    if set(by_id) - set(state.consumed_function_call_ids) != pending_ids:
        raise GoogleInteractionsProtocolError("provider_tool_result_pairing_invalid")
    steps = []
    for pending in state.pending_function_calls:
        result = by_id.get(pending.call_id)
        if result is None or result.provider_tool_name != pending.name:
            raise GoogleInteractionsProtocolError("provider_tool_result_pairing_invalid")
        text = _decode_utf8(result.content)
        try:
            json.loads(text)
        except json.JSONDecodeError as error:
            raise GoogleInteractionsProtocolError("provider_tool_result_pairing_invalid") from error
        step: dict[str, object] = {
            "type": "function_result",
            "name": pending.name,
            "call_id": pending.call_id,
            "result": [{"type": "text", "text": text}],
        }
        if result.is_error:
            step["is_error"] = True
        steps.append(step)
    return steps


def _tool_results_by_id(
    results: tuple[AgenticToolResult, ...],
) -> dict[str, AgenticToolResult]:
    by_id = {item.provider_tool_call_id: item for item in results}
    if len(by_id) != len(results):
        raise GoogleInteractionsProtocolError("provider_tool_result_pairing_invalid")
    return by_id


def _system_instruction(request: AgenticModelRequest) -> str:
    values = []
    for block in request.content_blocks:
        if block.role != "system":
            continue
        if not block.content_type.startswith("text/"):
            raise GoogleInteractionsProtocolError("provider_request_invalid")
        values.append(_decode_utf8(block.content))
    return "\n\n".join(values)


def _thinking_level(reasoning_effort: str | None) -> dict[str, str]:
    if reasoning_effort is None:
        return {}
    normalized = reasoning_effort.strip().lower()
    if normalized not in {"minimal", "low", "medium", "high"}:
        raise GoogleInteractionsProtocolError("provider_request_invalid")
    return {"thinking_level": normalized}


def _decode_utf8(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GoogleInteractionsProtocolError("provider_request_invalid") from error
