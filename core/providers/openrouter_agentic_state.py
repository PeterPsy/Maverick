"""Encode and strictly validate opaque OpenRouter continuation state."""

from __future__ import annotations

import json

from core.providers.agentic_protocol import AgenticProviderPrivateState
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
    OpenRouterAgenticProtocolError,
    OpenRouterChatState,
    OpenRouterPendingToolCall,
)


MAX_OPENROUTER_PRIVATE_STATE_BYTES = 2 * 1_048_576


def initial_openrouter_chat_state() -> OpenRouterChatState:
    return OpenRouterChatState(
        schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
        history=(),
        pending_tool_call=None,
        consumed_tool_call_ids=(),
    )


def decode_openrouter_chat_state(
    private_state: AgenticProviderPrivateState | None,
) -> OpenRouterChatState:
    if private_state is None:
        return initial_openrouter_chat_state()
    identity = (
        private_state.codec_id,
        private_state.codec_version,
        private_state.schema_version,
        private_state.content_type,
    )
    if identity != (
        OPENROUTER_AGENTIC_CODEC_ID,
        OPENROUTER_AGENTIC_CODEC_VERSION,
        OPENROUTER_AGENTIC_SCHEMA_VERSION,
        OPENROUTER_AGENTIC_CONTENT_TYPE,
    ) or len(private_state.content) > MAX_OPENROUTER_PRIVATE_STATE_BYTES:
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
    try:
        payload = json.loads(private_state.content)
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "history",
            "pending_tool_call",
            "consumed_tool_call_ids",
        }:
            raise ValueError
        history = payload["history"]
        consumed = payload["consumed_tool_call_ids"]
        if (
            payload["schema_version"] != OPENROUTER_AGENTIC_SCHEMA_VERSION
            or not isinstance(history, list)
            or not isinstance(consumed, list)
            or not all(isinstance(value, str) and value for value in consumed)
            or len(set(consumed)) != len(consumed)
        ):
            raise ValueError
        validated_history = tuple(_history_message(value) for value in history)
        pending = _pending_tool_call(payload["pending_tool_call"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as cause:
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid") from cause
    if pending is not None and pending.call_id in consumed:
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
    state = OpenRouterChatState(
        schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
        history=validated_history,
        pending_tool_call=pending,
        consumed_tool_call_ids=tuple(consumed),
    )
    _validate_state_relationships(state)
    return state


def encode_openrouter_chat_state(state: OpenRouterChatState) -> AgenticProviderPrivateState:
    _validate_state_relationships(state)
    payload = {
        "schema_version": state.schema_version,
        "history": state.history,
        "pending_tool_call": (
            None
            if state.pending_tool_call is None
            else {
                "call_id": state.pending_tool_call.call_id,
                "name": state.pending_tool_call.name,
            }
        ),
        "consumed_tool_call_ids": state.consumed_tool_call_ids,
    }
    try:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as cause:
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid") from cause
    if len(content) > MAX_OPENROUTER_PRIVATE_STATE_BYTES:
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
    return AgenticProviderPrivateState(
        codec_id=OPENROUTER_AGENTIC_CODEC_ID,
        codec_version=OPENROUTER_AGENTIC_CODEC_VERSION,
        schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
        content_type=OPENROUTER_AGENTIC_CONTENT_TYPE,
        content=content,
    )


def _pending_tool_call(value: object) -> OpenRouterPendingToolCall | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"call_id", "name"}:
        raise ValueError
    call_id = value.get("call_id")
    name = value.get("name")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        raise ValueError
    return OpenRouterPendingToolCall(call_id, name)


def _history_message(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError
    role = value.get("role")
    if role in {"system", "user"}:
        if set(value) != {"role", "content"} or not isinstance(value.get("content"), str):
            raise ValueError
    elif role == "tool":
        if set(value) != {"role", "tool_call_id", "content"}:
            raise ValueError
        if not isinstance(value.get("tool_call_id"), str) or not isinstance(value.get("content"), str):
            raise ValueError
    elif role == "assistant":
        _validate_assistant_message(value)
    else:
        raise ValueError
    return dict(value)


def _validate_assistant_message(value: dict[str, object]) -> None:
    allowed = {"role", "content", "tool_calls", "reasoning", "reasoning_details"}
    if not set(value).issubset(allowed) or not isinstance(value.get("content"), (str, type(None))):
        raise ValueError
    if "reasoning" in value and not isinstance(value["reasoning"], str):
        raise ValueError
    details = value.get("reasoning_details", [])
    if not isinstance(details, list) or not all(isinstance(item, dict) for item in details):
        raise ValueError
    calls = value.get("tool_calls", [])
    if not isinstance(calls, list) or len(calls) > 1:
        raise ValueError
    for call in calls:
        if not isinstance(call, dict) or set(call) != {"id", "type", "function"}:
            raise ValueError
        function = call.get("function")
        if (
            call.get("type") != "function"
            or not isinstance(call.get("id"), str)
            or not isinstance(function, dict)
            or set(function) != {"name", "arguments"}
            or not isinstance(function.get("name"), str)
            or not isinstance(function.get("arguments"), str)
        ):
            raise ValueError


def _validate_state_relationships(state: OpenRouterChatState) -> None:
    pending: OpenRouterPendingToolCall | None = None
    consumed: list[str] = []
    seen_ids: set[str] = set()
    for message in state.history:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            if pending is not None:
                raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
            call = message["tool_calls"][0]
            function = call["function"]
            call_id = str(call["id"])
            if call_id in seen_ids:
                raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
            seen_ids.add(call_id)
            pending = OpenRouterPendingToolCall(call_id, str(function["name"]))
        elif role == "tool":
            if pending is None or message.get("tool_call_id") != pending.call_id:
                raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
            consumed.append(pending.call_id)
            pending = None
    if pending != state.pending_tool_call or tuple(consumed) != state.consumed_tool_call_ids:
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
