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
from core.runtime.hosted_agentic_models import HostedProviderStateInspection


MAX_OPENROUTER_PRIVATE_STATE_BYTES = 2 * 1_048_576


def initial_openrouter_chat_state() -> OpenRouterChatState:
    return OpenRouterChatState(
        schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
        history=(),
        pending_tool_calls=(),
        consumed_tool_call_ids=(),
    )


def merge_openrouter_request_history(
    history: tuple[dict[str, object], ...],
    new_messages: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """Replace request-scoped authority blocks and append exact new dialogue."""
    systems = tuple(
        dict(item) for item in new_messages if item.get("role") == "system"
    )
    if len(systems) > 1:
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    retained = tuple(
        dict(item) for item in history if item.get("role") != "system"
    )
    additions = tuple(
        dict(item) for item in new_messages if item.get("role") != "system"
    )
    # System/developer authority is request scoped.  Even an empty current
    # projection must not resurrect a stale authority block from private
    # history.
    return (*systems, *retained, *additions)


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
            "pending_tool_calls",
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
        raw_pending = payload["pending_tool_calls"]
        if not isinstance(raw_pending, list):
            raise ValueError
        pending = tuple(_pending_tool_call(item) for item in raw_pending)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as cause:
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid") from cause
    if (
        len({item.call_id for item in pending}) != len(pending)
        or {item.call_id for item in pending}.intersection(consumed)
    ):
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
    state = OpenRouterChatState(
        schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
        history=validated_history,
        pending_tool_calls=pending,
        consumed_tool_call_ids=tuple(consumed),
    )
    _validate_state_relationships(state)
    return state


def encode_openrouter_chat_state(state: OpenRouterChatState) -> AgenticProviderPrivateState:
    _validate_state_relationships(state)
    payload = {
        "schema_version": state.schema_version,
        "history": state.history,
        "pending_tool_calls": [
            {"call_id": item.call_id, "name": item.name}
            for item in state.pending_tool_calls
        ],
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


def inspect_openrouter_chat_state(content: bytes) -> HostedProviderStateInspection:
    """Decode recovery facts through the exact current OpenRouter codec."""
    state = decode_openrouter_chat_state(
        AgenticProviderPrivateState(
            codec_id=OPENROUTER_AGENTIC_CODEC_ID,
            codec_version=OPENROUTER_AGENTIC_CODEC_VERSION,
            schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
            content_type=OPENROUTER_AGENTIC_CONTENT_TYPE,
            content=content,
        )
    )
    return HostedProviderStateInspection(
        pending_tool_calls=tuple(
            (item.call_id, item.name) for item in state.pending_tool_calls
        ),
        consumed_tool_call_ids=state.consumed_tool_call_ids,
    )


def _pending_tool_call(value: object) -> OpenRouterPendingToolCall:
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
    if not isinstance(calls, list):
        raise ValueError
    call_ids: set[str] = set()
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
        if call["id"] in call_ids:
            raise ValueError
        call_ids.add(call["id"])


def _validate_state_relationships(state: OpenRouterChatState) -> None:
    pending: list[OpenRouterPendingToolCall] = []
    consumed: list[str] = []
    seen_ids: set[str] = set()
    for message in state.history:
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            if pending:
                raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
            for call in message["tool_calls"]:
                function = call["function"]
                call_id = str(call["id"])
                if call_id in seen_ids:
                    raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
                seen_ids.add(call_id)
                pending.append(
                    OpenRouterPendingToolCall(call_id, str(function["name"]))
                )
        elif role == "tool":
            if not pending or message.get("tool_call_id") != pending[0].call_id:
                raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
            consumed.append(pending.pop(0).call_id)
    if tuple(pending) != state.pending_tool_calls or tuple(consumed) != state.consumed_tool_call_ids:
        raise OpenRouterAgenticProtocolError("provider_private_state_invalid")
