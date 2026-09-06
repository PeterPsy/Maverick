"""Translate provider-neutral requests into fail-closed OpenRouter payloads."""

from __future__ import annotations

from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticToolResult,
    HOSTED_FINALIZATION_INSTRUCTION,
)
from core.providers.openrouter_agentic_models import (
    OpenRouterAgenticProtocolError,
    OpenRouterChatState,
)
from core.providers.openrouter_agentic_state import merge_openrouter_request_history


def openrouter_chat_payload(
    request: AgenticModelRequest,
    state: OpenRouterChatState,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    """Return the exact certified payload and messages newly added this step."""
    _validate_routing(request)
    _validate_request_phase(request)
    new_messages = _new_messages(request, state)
    messages = list(merge_openrouter_request_history(state.history, new_messages))
    finalization_instruction = _finalization_instruction(request)
    if finalization_instruction is not None:
        messages.append({"role": "system", "content": finalization_instruction})
    if not messages:
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    payload: dict[str, object] = {
        "model": request.model_id,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": request.max_output_tokens,
        "provider": {
            "only": list(request.routing_constraint.allowed_upstream_ids),
            "allow_fallbacks": request.routing_constraint.allow_fallbacks,
            "require_parameters": request.routing_constraint.require_parameters,
            "data_collection": request.routing_constraint.data_collection_policy,
            "zdr": request.routing_constraint.require_zdr,
            "quantizations": list(
                request.routing_constraint.allowed_quantizations
            ),
        },
    }
    # No offered tools means neither tool parameter is sent. In particular,
    # finalization does not require an endpoint's unsupported explicit-none mode.
    if request.tool_definitions:
        payload["tools"] = [
            {"type": "function", "function": {
                "name": tool.name, "description": tool.description,
                "parameters": tool.input_schema,
            }}
            for tool in request.tool_definitions
        ]
        payload["tool_choice"] = "auto"
    if request.reasoning_effort is not None:
        effort = request.reasoning_effort.strip().lower()
        if effort not in {"minimal", "low", "medium", "high"}:
            raise OpenRouterAgenticProtocolError("provider_request_invalid")
        payload["reasoning"] = {"effort": effort}
    return payload, new_messages


def _validate_routing(request: AgenticModelRequest) -> None:
    routing = request.routing_constraint
    if (
        not str(routing.endpoint_id or "").strip()
        or len(routing.allowed_upstream_ids) != 1
        or not str(routing.allowed_upstream_ids[0] or "").strip()
        or routing.allow_fallbacks
        or not routing.require_parameters
        or routing.data_collection_policy != "deny"
        or not routing.require_zdr
        or not routing.allowed_quantizations
        or any(
            not str(value or "").strip()
            for value in routing.allowed_quantizations
        )
        or len(set(routing.allowed_quantizations))
        != len(routing.allowed_quantizations)
    ):
        raise OpenRouterAgenticProtocolError("provider_routing_not_certified")


def _new_messages(
    request: AgenticModelRequest,
    state: OpenRouterChatState,
) -> tuple[dict[str, object], ...]:
    system_message, user_messages = _request_content_messages(request)
    by_id = _tool_results_by_id(request.tool_results)
    pending = state.pending_tool_calls
    consumed = set(state.consumed_tool_call_ids)
    if pending:
        _validate_pairing_lineage(request)
        pending_ids = {item.call_id for item in pending}
        if set(by_id) - consumed != pending_ids:
            raise OpenRouterAgenticProtocolError("provider_tool_result_pairing_invalid")
        messages = []
        if system_message is not None:
            messages.append(system_message)
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
        # New governed user blocks follow the mandatory assistant/tool pairing.
        # Exact blocks already retained in private history need not be replayed.
        for message in user_messages:
            if message not in state.history:
                messages.append(message)
        return tuple(messages)
    if any(
        value is not None
        for value in (
            request.pairing_source_journal_id,
            request.pairing_source_turn_id,
            request.pairing_source_request_id,
        )
    ):
        raise OpenRouterAgenticProtocolError("provider_tool_result_pairing_invalid")
    if set(by_id) - consumed:
        raise OpenRouterAgenticProtocolError("provider_tool_result_pairing_invalid")
    if not user_messages:
        raise OpenRouterAgenticProtocolError("provider_request_invalid")
    return (
        *((system_message,) if system_message is not None else ()),
        *user_messages,
    )


def _request_content_messages(
    request: AgenticModelRequest,
) -> tuple[dict[str, object] | None, tuple[dict[str, object], ...]]:
    system_values: list[str] = []
    user_messages: list[dict[str, object]] = []
    for block in request.content_blocks:
        if block.provenance == "finalization_instruction":
            continue
        if block.role not in {"system", "developer", "user"} or not _textual_content_type(
            block.content_type
        ):
            raise OpenRouterAgenticProtocolError("provider_request_invalid")
        content = _decode_utf8(block.content)
        if block.role in {"system", "developer"}:
            system_values.append(content)
            continue
        user_messages.append({"role": "user", "content": content})
    system_message = (
        None
        if not system_values
        else {"role": "system", "content": "\n\n".join(system_values)}
    )
    return system_message, tuple(user_messages)


def _validate_request_phase(request: AgenticModelRequest) -> None:
    finalization_blocks = tuple(
        block
        for block in request.content_blocks
        if block.provenance == "finalization_instruction"
    )
    if request.request_phase == "exploration":
        if finalization_blocks:
            raise OpenRouterAgenticProtocolError("provider_request_invalid")
        return
    if (
        request.request_phase not in {"finalization", "finalization_recovery"}
        or request.tool_definitions
        or len(finalization_blocks) != 1
        or not request.content_blocks
        or request.content_blocks[-1] != finalization_blocks[0]
        or finalization_blocks[0].role != "system"
        or finalization_blocks[0].data_class != "public"
        or finalization_blocks[0].trust_level != "trusted_platform"
        or finalization_blocks[0].content_type != "text/plain"
        or finalization_blocks[0].content
        != HOSTED_FINALIZATION_INSTRUCTION.encode("utf-8")
    ):
        raise OpenRouterAgenticProtocolError("provider_request_invalid")


def _finalization_instruction(request: AgenticModelRequest) -> str | None:
    if request.request_phase == "exploration":
        return None
    block = next(
        item
        for item in request.content_blocks
        if item.provenance == "finalization_instruction"
    )
    return _decode_utf8(block.content)


def _validate_pairing_lineage(request: AgenticModelRequest) -> None:
    state = request.provider_private_state
    if (
        not request.pairing_source_journal_id
        or not request.pairing_source_turn_id
        or not request.pairing_source_request_id
        or request.correlation_id != request.pairing_source_turn_id
        or state is None
        or state.provider_request_id != request.pairing_source_request_id
        or state.turn_generation != request.pairing_source_turn_id
    ):
        raise OpenRouterAgenticProtocolError("provider_tool_result_pairing_invalid")


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
