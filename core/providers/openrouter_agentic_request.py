"""Translate provider-neutral requests into fail-closed OpenRouter payloads."""

from __future__ import annotations

from core.providers.agentic_protocol import AgenticModelRequest, AgenticToolResult
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_ENDPOINT_ID,
    OPENROUTER_AGENTIC_UPSTREAM_ID,
    OpenRouterAgenticProtocolError,
    OpenRouterChatState,
)


def openrouter_chat_payload(
    request: AgenticModelRequest,
    state: OpenRouterChatState,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    """Return the exact certified payload and messages newly added this step."""
    _validate_routing(request)
    new_messages = _new_messages(request, state)
    messages = [*state.history, *new_messages]
    if not messages:
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    payload: dict[str, object] = {
        "model": request.model_id,
        "messages": messages,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in request.tool_definitions
        ],
        "tool_choice": "auto" if request.tool_definitions else "none",
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": request.max_output_tokens,
        "provider": {
            "only": [OPENROUTER_AGENTIC_UPSTREAM_ID],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            "zdr": True,
            "quantizations": ["fp8"],
        },
    }
    if request.reasoning_effort is not None:
        effort = request.reasoning_effort.strip().lower()
        if effort not in {"minimal", "low", "medium", "high"}:
            raise OpenRouterAgenticProtocolError("provider_request_invalid")
        payload["reasoning"] = {"effort": effort}
    return payload, new_messages


def _validate_routing(request: AgenticModelRequest) -> None:
    routing = request.routing_constraint
    if (
        routing.endpoint_id != OPENROUTER_AGENTIC_ENDPOINT_ID
        or routing.allowed_upstream_ids != (OPENROUTER_AGENTIC_UPSTREAM_ID,)
        or routing.allow_fallbacks
        or not routing.require_parameters
        or routing.data_collection_policy != "deny"
        or not routing.require_zdr
        or routing.allowed_quantizations != ("fp8",)
    ):
        raise OpenRouterAgenticProtocolError("provider_routing_not_certified")


def _new_messages(
    request: AgenticModelRequest,
    state: OpenRouterChatState,
) -> tuple[dict[str, object], ...]:
    by_id = _tool_results_by_id(request.tool_results)
    pending = state.pending_tool_calls
    consumed = set(state.consumed_tool_call_ids)
    if pending:
        pending_ids = {item.call_id for item in pending}
        if set(by_id) - consumed != pending_ids:
            raise OpenRouterAgenticProtocolError("provider_tool_result_pairing_invalid")
        messages = []
        for item in pending:
            result = by_id[item.call_id]
            if result.provider_tool_name != item.name:
                raise OpenRouterAgenticProtocolError(
                    "provider_tool_result_pairing_invalid"
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.call_id,
                    "content": _decode_utf8(result.content, pairing=True),
                }
            )
        return tuple(messages)
    if set(by_id) - consumed:
        raise OpenRouterAgenticProtocolError("provider_tool_result_pairing_invalid")
    values: list[dict[str, object]] = []
    existing_system = next(
        (item for item in state.history if item.get("role") == "system"),
        None,
    )
    system_values: list[str] = []
    for block in request.content_blocks:
        if block.role not in {"system", "user"} or not _textual_content_type(
            block.content_type
        ):
            raise OpenRouterAgenticProtocolError("provider_request_invalid")
        content = _decode_utf8(block.content)
        if block.role == "system":
            system_values.append(content)
            continue
        values.append({"role": "user", "content": content})
    if system_values:
        system_message = {"role": "system", "content": "\n\n".join(system_values)}
        if existing_system is not None:
            if system_message != existing_system:
                raise OpenRouterAgenticProtocolError("provider_request_invalid")
        else:
            values.insert(0, system_message)
    if not any(item["role"] == "user" for item in values):
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    return tuple(values)


def _textual_content_type(value: str) -> bool:
    return value.startswith("text/") or value == "application/json"


def _tool_results_by_id(
    results: tuple[AgenticToolResult, ...],
) -> dict[str, AgenticToolResult]:
    by_id = {item.provider_tool_call_id: item for item in results}
    if len(by_id) != len(results):
        raise OpenRouterAgenticProtocolError("provider_tool_result_pairing_invalid")
    return by_id


def _decode_utf8(content: bytes, *, pairing: bool = False) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as cause:
        reason = "provider_tool_result_pairing_invalid" if pairing else "provider_request_invalid"
        raise OpenRouterAgenticProtocolError(reason) from cause
