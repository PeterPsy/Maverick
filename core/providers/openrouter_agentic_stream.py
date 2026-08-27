"""Strict OpenRouter streaming Chat Completions event assembler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json

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
        self.tool_calls: dict[int, _ToolCall] = {}
        self.emitted_tool_calls: tuple[AgenticToolCall, ...] | None = None
        self._tool_events: tuple[AgenticModelEvent, ...] = ()
        self._tool_events_delivered = False
        self.finish_reason: str | None = None
        self.usage: AgenticUsage | None = None
        self.usage_emitted = False
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
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        if choices:
            events.extend(self._choice(object_field(choices[0])))
        if metadata is not None:
            if self.saw_router_metadata:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            validate_router_metadata(metadata, model_id=self.request.model_id)
            self.saw_router_metadata = True
        if payload.get("usage") is not None:
            if self.usage is not None:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.usage = self._usage(payload["usage"])
        if self.finish_reason is not None and self.usage is not None and self.saw_router_metadata:
            events.extend(self._complete())
        if self._tool_events and any(item in events for item in self._tool_events):
            self._tool_events_delivered = True
        return events

    def finish(self) -> None:
        if not self.completed:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")

    def failure_telemetry(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        """Recover only redaction-safe identity/usage after a terminal decode error."""
        if self.usage_emitted:
            return []
        try:
            generation_id = required_text(payload.get("id"))
            if (
                self.generation_id is None
                or generation_id != self.generation_id
                or payload.get("model") != self.request.model_id
                or payload.get("provider") != OPENROUTER_AGENTIC_PROVIDER_NAME
            ):
                return []
            raw_usage = payload.get("usage")
            if raw_usage is not None:
                recovered = self._usage(raw_usage)
                if self.usage is not None and recovered != self.usage:
                    return []
                self.usage = recovered
            if self.usage is None:
                return []
            self.usage_emitted = True
            return [self._event("usage", usage=self.usage)]
        except OpenRouterAgenticProtocolError:
            return []

    def failure_observed_tool_events(self) -> list[AgenticModelEvent]:
        """Return calls assembled before a later terminal-field failure exactly once."""
        if not self._tool_events and self.tool_calls:
            try:
                self._tool_call_events()
            except OpenRouterAgenticProtocolError:
                return []
        if self._tool_events_delivered or not self._tool_events:
            return []
        self._tool_events_delivered = True
        return list(self._tool_events)

    def _identity(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        generation_id = required_text(payload.get("id"))
        if (
            payload.get("model") != self.request.model_id
            or payload.get("provider") != OPENROUTER_AGENTIC_PROVIDER_NAME
        ):
            raise OpenRouterAgenticProtocolError("provider_upstream_not_certified")
        if self.generation_id is None:
            self.generation_id = generation_id
            return [self._event(
                "accepted",
                upstream_id=OPENROUTER_AGENTIC_UPSTREAM_ID,
                provider_response_id=generation_id,
            )]
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
                or delta.get("role") not in {None, "assistant"}
                or delta.get("content") not in {None, ""}
                or any(delta.get(field) is not None for field in (
                    "reasoning", "reasoning_content", "reasoning_details", "tool_calls",
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
            if not isinstance(content, str):
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            if content:
                self.text_chunks.append(content)
        self._reasoning(delta)
        if delta.get("tool_calls") is not None:
            self._tool_delta(delta["tool_calls"])
        if finish_reason is not None:
            if finish_reason not in {"stop", "tool_calls"}:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.finish_reason = finish_reason
            if finish_reason == "tool_calls":
                events.extend(self._tool_call_events())
        return events

    def _reasoning(self, delta: dict[str, object]) -> None:
        self.reasoning_details.extend(reasoning_details(delta.get("reasoning_details")))
        raw = delta.get("reasoning", delta.get("reasoning_content"))
        if raw is not None:
            if not isinstance(raw, str):
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            self.reasoning_chunks.append(raw)

    def _tool_delta(self, value: object) -> None:
        if not isinstance(value, list) or not value:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        for raw_item in value:
            item = object_field(raw_item)
            index = nonnegative_int(item.get("index"))
            self._tool_call_delta(index, item)

    def _tool_call_delta(self, index: int, item: dict[str, object]) -> None:
        tool_call = self.tool_calls.setdefault(index, _ToolCall())
        call_id = item.get("id")
        if call_id is not None:
            call_id = required_text(call_id)
            if tool_call.call_id not in {None, call_id}:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            tool_call.call_id = call_id
        if item.get("type") not in {None, "function"}:
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        function = object_field(item.get("function"))
        name = function.get("name")
        if name is not None:
            name = required_text(name)
            if tool_call.name not in {None, name}:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            tool_call.name = name
        arguments = function.get("arguments")
        if arguments is not None:
            if not isinstance(arguments, str):
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            tool_call.argument_chunks.append(arguments)

    def _tool_call_events(self) -> list[AgenticModelEvent]:
        """Emit every complete indexed call before later terminal fields can fail."""
        if self.emitted_tool_calls is not None:
            return []
        if not self.tool_calls or set(self.tool_calls) != set(range(len(self.tool_calls))):
            raise OpenRouterAgenticProtocolError("provider_tool_call_index_invalid")
        calls: list[AgenticToolCall] = []
        seen_ids: set[str] = set()
        for index in range(len(self.tool_calls)):
            assembled = self.tool_calls[index]
            call_id = required_text(assembled.call_id)
            name = required_text(assembled.name)
            if call_id in seen_ids:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            seen_ids.add(call_id)
            raw_text = "".join(assembled.argument_chunks)
            raw_arguments = raw_text.encode("utf-8") or b'""'
            try:
                parsed = json.loads(
                    raw_text,
                    parse_constant=_reject_json_constant,
                )
            except (json.JSONDecodeError, ValueError):
                parsed = None
            arguments = dict(parsed) if isinstance(parsed, dict) else None
            calls.append(
                AgenticToolCall(
                    provider_tool_call_id=call_id,
                    provider_tool_name=name,
                    arguments=arguments,
                    call_index=index,
                    arguments_raw=(raw_arguments if arguments is None else None),
                )
            )
        self.emitted_tool_calls = tuple(calls)
        self._tool_events = tuple(
            self._event("tool_call", tool_call=call) for call in calls
        )
        return list(self._tool_events)

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
            if self.emitted_tool_calls is None:
                self._tool_call_events()
            if not self.emitted_tool_calls:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            assistant_calls = []
            pending = []
            for index, call in enumerate(self.emitted_tool_calls):
                assembled = self.tool_calls[index]
                raw_arguments = "".join(assembled.argument_chunks)
                assistant_calls.append({
                    "id": call.provider_tool_call_id,
                    "type": "function",
                    "function": {
                        "name": call.provider_tool_name,
                        "arguments": raw_arguments,
                    },
                })
                pending.append(
                    OpenRouterPendingToolCall(
                        call.provider_tool_call_id,
                        call.provider_tool_name,
                    )
                )
            assistant = self._assistant_message(
                content="".join(self.text_chunks) or None,
                tool_calls=assistant_calls,
            )
            result = []
        else:
            if self.tool_calls and self.text_chunks:
                raise OpenRouterAgenticProtocolError("provider_mixed_text_and_tool_call")
            if self.tool_calls or not self.text_chunks:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            text = "".join(self.text_chunks)
            assistant = self._assistant_message(content=text)
            pending = []
            result = [
                self._event("text_delta", text=chunk)
                for chunk in self.text_chunks
            ]
        consumed = list(self.state.consumed_tool_call_ids)
        consumed.extend(item.call_id for item in self.state.pending_tool_calls)
        if {item.call_id for item in pending}.intersection(consumed):
            raise OpenRouterAgenticProtocolError("provider_response_invalid")
        private_state = encode_openrouter_chat_state(
            OpenRouterChatState(
                schema_version=self.state.schema_version,
                history=(*self.state.history, *self.new_messages, assistant),
                pending_tool_calls=tuple(pending),
                consumed_tool_call_ids=tuple(consumed),
            )
        )
        result.extend(
            [
                self._event("provider_state", provider_private_state=private_state),
                self._usage_event(),
            ]
        )
        if not pending:
            result.append(self._event("text_final", text="".join(self.text_chunks)))
        self.completed = True
        result.append(self._event("completed", finish_reason=str(self.finish_reason)))
        return result

    def _usage_event(self) -> AgenticModelEvent:
        self.usage_emitted = True
        return self._event("usage", usage=self.usage)

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


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")
