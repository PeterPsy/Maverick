"""Strict OpenRouter streaming Chat Completions event assembler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    AgenticToolCall,
    AgenticUsage,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_PROVIDER_NAME,
    OPENROUTER_AGENTIC_UPSTREAM_ID,
    OpenRouterAgenticProtocolError,
    OpenRouterChatState,
    OpenRouterPendingToolCall,
    openrouter_error_reason,
)
from core.providers.openrouter_agentic_state import encode_openrouter_chat_state
from core.providers.openrouter_agentic_stream_fields import (
    nonnegative_int,
    object_field,
    parsed_arguments,
    reasoning_details,
    required_text,
    validate_router_metadata,
)


OpenRouterUsageCost = Callable[[int, int], int | None]


@dataclass
class _ToolCall:
    call_id: str | None = None
    name: str | None = None
    argument_chunks: list[str] = field(default_factory=list)


class OpenRouterChatStreamDecoder:
    """Convert one certified stream into provider-neutral public events."""

    def __init__(
        self,
        *,
        request: AgenticModelRequest,
        state: OpenRouterChatState,
        new_messages: tuple[dict[str, object], ...],
        usage_cost: OpenRouterUsageCost,
    ) -> None:
        self.request = request
        self.state = state
        self.new_messages = new_messages
        self.usage_cost = usage_cost
        self.generation_id: str | None = None
        self.text_chunks: list[str] = []
        self.reasoning_chunks: list[str] = []
        self.reasoning_details: list[dict[str, object]] = []
        self.tool_call: _ToolCall | None = None
        self.finish_reason: str | None = None
        self.usage: AgenticUsage | None = None
        self.saw_router_metadata = False
        self.ordinal = 0
        self.completed = False

    def feed(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        if self.completed:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        if "error" in payload:
            self.completed = True
            return [self._event("error", error_code=openrouter_error_reason(payload))]
        events = self._identity(payload)
        metadata = payload.get("openrouter_metadata")
        if metadata is not None:
            if self.saw_router_metadata:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            validate_router_metadata(metadata, model_id=self.request.model_id)
            self.saw_router_metadata = True
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        if choices:
            events.extend(self._choice(object_field(choices[0])))
        if payload.get("usage") is not None:
            if self.usage is not None:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.usage = self._usage(payload["usage"])
        if self.finish_reason is not None and self.usage is not None and self.saw_router_metadata:
            events.extend(self._complete())
        return events

    def finish(self) -> None:
        if not self.completed:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")

    def _identity(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        generation_id = required_text(payload.get("id"))
        if (
            payload.get("model") != self.request.model_id
            or payload.get("provider") != OPENROUTER_AGENTIC_PROVIDER_NAME
        ):
            raise OpenRouterAgenticProtocolError("provider_upstream_not_certified")
        if self.generation_id is None:
            self.generation_id = generation_id
            return [self._event("accepted", upstream_id=OPENROUTER_AGENTIC_UPSTREAM_ID)]
        if generation_id != self.generation_id:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        return []

    def _choice(self, choice: dict[str, object]) -> list[AgenticModelEvent]:
        if choice.get("index") != 0:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        delta = object_field(choice.get("delta"))
        finish_reason = choice.get("finish_reason")
        if self.finish_reason is not None:
            if (
                finish_reason != self.finish_reason
                or any(delta.get(field) is not None for field in (
                    "role", "content", "reasoning", "reasoning_content",
                    "reasoning_details", "tool_calls",
                ))
            ):
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            return []
        events: list[AgenticModelEvent] = []
        role = delta.get("role")
        if role is not None and role != "assistant":
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str) or (content and self.tool_call is not None):
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            if content:
                self.text_chunks.append(content)
                events.append(self._event("text_delta", text=content))
        self._reasoning(delta)
        if delta.get("tool_calls") is not None:
            self._tool_delta(delta["tool_calls"])
        if finish_reason is not None:
            if finish_reason not in {"stop", "tool_calls"}:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.finish_reason = finish_reason
        return events

    def _reasoning(self, delta: dict[str, object]) -> None:
        self.reasoning_details.extend(reasoning_details(delta.get("reasoning_details")))
        raw = delta.get("reasoning", delta.get("reasoning_content"))
        if raw is not None:
            if not isinstance(raw, str):
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.reasoning_chunks.append(raw)

    def _tool_delta(self, value: object) -> None:
        if self.text_chunks or not isinstance(value, list) or len(value) != 1:
            raise OpenRouterAgenticProtocolError("provider_parallel_tool_calls_forbidden")
        item = object_field(value[0])
        if item.get("index") != 0:
            raise OpenRouterAgenticProtocolError("provider_parallel_tool_calls_forbidden")
        if self.tool_call is None:
            self.tool_call = _ToolCall()
        call_id = item.get("id")
        if call_id is not None:
            call_id = required_text(call_id)
            if self.tool_call.call_id not in {None, call_id}:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.tool_call.call_id = call_id
        if item.get("type") not in {None, "function"}:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        function = object_field(item.get("function"))
        name = function.get("name")
        if name is not None:
            name = required_text(name)
            if self.tool_call.name not in {None, name}:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.tool_call.name = name
        arguments = function.get("arguments")
        if arguments is not None:
            if not isinstance(arguments, str):
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.tool_call.argument_chunks.append(arguments)

    def _usage(self, value: object) -> AgenticUsage:
        usage = object_field(value)
        input_tokens = nonnegative_int(usage.get("prompt_tokens"))
        output_tokens = nonnegative_int(usage.get("completion_tokens"))
        return AgenticUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_microusd=self.usage_cost(input_tokens, output_tokens),
        )

    def _complete(self) -> list[AgenticModelEvent]:
        if self.finish_reason == "tool_calls":
            if self.tool_call is None or self.text_chunks:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            call_id = required_text(self.tool_call.call_id)
            name = required_text(self.tool_call.name)
            raw_arguments = "".join(self.tool_call.argument_chunks)
            arguments = parsed_arguments(raw_arguments)
            assistant = self._assistant_message(
                content=None,
                tool_calls=[{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": raw_arguments},
                }],
            )
            pending = OpenRouterPendingToolCall(call_id, name)
            result = [
                self._event(
                    "tool_call",
                    tool_call=AgenticToolCall(call_id, name, arguments),
                )
            ]
        else:
            if self.tool_call is not None or not self.text_chunks:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            text = "".join(self.text_chunks)
            assistant = self._assistant_message(content=text)
            pending = None
            result = []
        consumed = list(self.state.consumed_tool_call_ids)
        if self.state.pending_tool_call is not None:
            consumed.append(self.state.pending_tool_call.call_id)
        if pending is not None and pending.call_id in consumed:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        private_state = encode_openrouter_chat_state(
            OpenRouterChatState(
                schema_version=self.state.schema_version,
                history=(*self.state.history, *self.new_messages, assistant),
                pending_tool_call=pending,
                consumed_tool_call_ids=tuple(consumed),
            )
        )
        result.extend(
            [
                self._event("provider_state", provider_private_state=private_state),
                self._event("usage", usage=self.usage),
            ]
        )
        if pending is None:
            result.append(self._event("text_final", text="".join(self.text_chunks)))
        self.completed = True
        result.append(self._event("completed", finish_reason=str(self.finish_reason)))
        return result

    def _assistant_message(self, *, content, tool_calls=None) -> dict[str, object]:
        message: dict[str, object] = {"role": "assistant", "content": content}
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        if self.reasoning_details:
            message["reasoning_details"] = self.reasoning_details
        elif self.reasoning_chunks:
            message["reasoning"] = "".join(self.reasoning_chunks)
        return message

    def _event(self, event_type: str, **values) -> AgenticModelEvent:
        self.ordinal += 1
        return AgenticModelEvent(
            event_type=event_type,
            request_id=self.request.request_id,
            ordinal=self.ordinal,
            **values,
        )
