"""Strict SSE event assembler for Google Gemini Interactions responses."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Callable

from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    AgenticToolCall,
    AgenticUsage,
)
from core.providers.google_interactions_models import (
    GoogleInteractionState,
    GoogleInteractionsProtocolError,
    GooglePendingFunctionCall,
    google_interaction_error_reason,
)
from core.providers.google_interactions_state import encode_google_interaction_state


GoogleUsageCost = Callable[[int, int], int | None]


@dataclass
class _Step:
    index: int
    step_type: str
    value: dict[str, object]
    argument_chunks: list[str] = field(default_factory=list)
    text_chunks: list[str] = field(default_factory=list)


class GoogleInteractionStreamDecoder:
    """Convert one exact Interactions stream into provider-neutral events."""

    def __init__(
        self,
        *,
        request: AgenticModelRequest,
        state: GoogleInteractionState,
        new_input: tuple[dict[str, object], ...],
        usage_cost: GoogleUsageCost,
    ) -> None:
        self.request = request
        self.state = state
        self.new_input = new_input
        self.usage_cost = usage_cost
        self.declared_function_names = frozenset(
            definition.name for definition in request.tool_definitions
        )
        self.interaction_id: str | None = None
        self.active_step: _Step | None = None
        self.steps: list[dict[str, object]] = []
        self.function_calls: list[GooglePendingFunctionCall] = []
        self.output_chunks: list[str] = []
        self.usage_emitted = False
        self.ordinal = 0
        self.completed = False

    def feed(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        event_type = payload.get("event_type")
        if event_type == "error":
            if self.completed:
                raise GoogleInteractionsProtocolError("provider_response_invalid")
            self.completed = True
            return [self._error(payload)]
        if event_type == "interaction.created":
            return [self._created(payload)]
        if self.interaction_id is None or self.completed:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        if event_type == "interaction.status_update":
            self._status_update(payload)
            return []
        if event_type == "step.start":
            self._start_step(payload)
            return []
        if event_type == "step.delta":
            return self._step_delta(payload)
        if event_type == "step.stop":
            return self._stop_step(payload)
        if event_type == "interaction.completed":
            return self._complete(payload)
        raise GoogleInteractionsProtocolError("provider_response_invalid")

    def finish(self) -> None:
        if not self.completed or self.active_step is not None:
            raise GoogleInteractionsProtocolError("provider_response_invalid")

    def failure_telemetry(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        """Recover only bounded usage after a terminal decode error."""
        if self.usage_emitted or payload.get("event_type") != "interaction.completed":
            return []
        try:
            interaction = _dict(payload.get("interaction"))
            if (
                self.interaction_id is None
                or interaction.get("id") != self.interaction_id
                or interaction.get("model") != self.request.model_id
            ):
                return []
            usage = _usage(interaction.get("usage"), self.usage_cost)
        except GoogleInteractionsProtocolError:
            return []
        self.usage_emitted = True
        return [self._event("usage", usage=usage)]

    def _created(self, payload: dict[str, object]) -> AgenticModelEvent:
        if self.interaction_id is not None:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        interaction = _dict(payload.get("interaction"))
        interaction_id = _required_text(interaction.get("id"))
        if interaction.get("model") != self.request.model_id:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        self.interaction_id = interaction_id
        return self._event("accepted")

    def _status_update(self, payload: dict[str, object]) -> None:
        if payload.get("interaction_id") not in {None, self.interaction_id}:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        if payload.get("status") not in {"in_progress", "requires_action"}:
            raise GoogleInteractionsProtocolError("provider_response_invalid")

    def _start_step(self, payload: dict[str, object]) -> None:
        if self.active_step is not None:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        index = _index(payload.get("index"))
        if index != len(self.steps):
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        value = _dict(payload.get("step"))
        step_type = value.get("type")
        if step_type not in {"thought", "model_output", "function_call"}:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        if step_type == "function_call":
            _required_text(value.get("id"))
            function_name = _required_text(value.get("name"))
            if function_name not in self.declared_function_names:
                raise GoogleInteractionsProtocolError("provider_tool_not_declared")
            arguments = value.get("arguments", {})
            if not isinstance(arguments, (dict, str)):
                raise GoogleInteractionsProtocolError("provider_response_invalid")
        self.active_step = _Step(index=index, step_type=step_type, value=dict(value))

    def _step_delta(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        step = self._matching_step(payload)
        delta = _dict(payload.get("delta"))
        delta_type = delta.get("type")
        if step.step_type == "model_output" and delta_type == "text":
            text = delta.get("text")
            if not isinstance(text, str):
                raise GoogleInteractionsProtocolError("provider_response_invalid")
            step.text_chunks.append(text)
            self.output_chunks.append(text)
            return [self._event("text_delta", text=text)]
        if step.step_type == "function_call" and delta_type in {"arguments_delta", "arguments"}:
            arguments = delta.get("arguments", delta.get("partial_arguments"))
            if not isinstance(arguments, str):
                raise GoogleInteractionsProtocolError("provider_response_invalid")
            step.argument_chunks.append(arguments)
            return []
        if step.step_type == "thought" and delta_type == "thought_signature":
            step.value["signature"] = _required_text(delta.get("signature"))
            return []
        if step.step_type == "thought" and delta_type == "thought_summary":
            content = delta.get("content")
            if not isinstance(content, dict):
                raise GoogleInteractionsProtocolError("provider_response_invalid")
            summary = step.value.setdefault("summary", [])
            if not isinstance(summary, list):
                raise GoogleInteractionsProtocolError("provider_response_invalid")
            summary.append(dict(content))
            return []
        raise GoogleInteractionsProtocolError("provider_response_invalid")

    def _stop_step(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        step = self._matching_step(payload)
        if step.step_type == "model_output":
            if not step.text_chunks:
                raise GoogleInteractionsProtocolError("provider_response_invalid")
            step.value = {
                "type": "model_output",
                "content": [{"type": "text", "text": "".join(step.text_chunks)}],
            }
        elif step.step_type == "function_call":
            if self.function_calls:
                raise GoogleInteractionsProtocolError("provider_parallel_tool_calls_forbidden")
            arguments = _function_arguments(step)
            step.value["arguments"] = arguments
            call = GooglePendingFunctionCall(
                call_id=_required_text(step.value.get("id")),
                name=_required_text(step.value.get("name")),
            )
            self.function_calls.append(call)
        else:
            if not isinstance(step.value.get("signature"), str):
                raise GoogleInteractionsProtocolError("provider_response_invalid")
        self.steps.append(step.value)
        self.active_step = None
        if step.step_type != "function_call":
            return []
        return [
            self._event(
                "tool_call",
                tool_call=AgenticToolCall(
                    provider_tool_call_id=self.function_calls[0].call_id,
                    provider_tool_name=self.function_calls[0].name,
                    arguments=dict(step.value["arguments"]),
                ),
            )
        ]

    def _complete(self, payload: dict[str, object]) -> list[AgenticModelEvent]:
        if self.active_step is not None:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        interaction = _dict(payload.get("interaction"))
        if interaction.get("id") != self.interaction_id or interaction.get("model") != self.request.model_id:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        status = interaction.get("status")
        if status == "requires_action":
            if len(self.function_calls) != 1 or self.output_chunks:
                raise GoogleInteractionsProtocolError("provider_response_invalid")
        elif status == "completed":
            if self.function_calls or not self.output_chunks:
                raise GoogleInteractionsProtocolError("provider_response_invalid")
        else:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        usage = _usage(interaction.get("usage"), self.usage_cost)
        history = (
            (*self.state.history, *self.new_input, *self.steps)
            if self.state.mode == "stateless"
            else ()
        )
        private_state = encode_google_interaction_state(
            GoogleInteractionState(
                schema_version=self.state.schema_version,
                mode=self.state.mode,
                previous_interaction_id=(self.interaction_id if self.state.mode == "stateful" else None),
                history=tuple(history),
                pending_function_calls=tuple(self.function_calls),
            )
        )
        events = [self._event("provider_state", provider_private_state=private_state)]
        self.usage_emitted = True
        events.append(self._event("usage", usage=usage))
        if status == "completed":
            events.append(self._event("text_final", text="".join(self.output_chunks)))
        self.completed = True
        events.append(self._event("completed", finish_reason=str(status)))
        return events

    def _error(self, payload: dict[str, object]) -> AgenticModelEvent:
        error = _dict(payload.get("error"))
        code = str(error.get("code") or "").strip().lower()
        return self._event("error", error_code=google_interaction_error_reason(code))

    def _matching_step(self, payload: dict[str, object]) -> _Step:
        if self.active_step is None or _index(payload.get("index")) != self.active_step.index:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        return self.active_step

    def _event(self, event_type: str, **values) -> AgenticModelEvent:
        self.ordinal += 1
        return AgenticModelEvent(
            event_type=event_type,
            request_id=self.request.request_id,
            ordinal=self.ordinal,
            **values,
        )


def _function_arguments(step: _Step) -> dict[str, object]:
    initial = step.value.get("arguments", {})
    if step.argument_chunks:
        if initial not in ({}, ""):
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        raw = "".join(step.argument_chunks)
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError as error:
            raise GoogleInteractionsProtocolError("provider_response_invalid") from error
    else:
        arguments = initial
    if not isinstance(arguments, dict):
        raise GoogleInteractionsProtocolError("provider_response_invalid")
    return dict(arguments)


def _usage(value: object, cost: GoogleUsageCost) -> AgenticUsage:
    usage = _dict(value)
    input_tokens = _nonnegative_int(usage.get("total_input_tokens"))
    output_tokens = _nonnegative_int(usage.get("total_output_tokens"))
    return AgenticUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_microusd=cost(input_tokens, output_tokens),
    )


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GoogleInteractionsProtocolError("provider_response_invalid")
    return value


def _index(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GoogleInteractionsProtocolError("provider_response_invalid")
    return value


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise GoogleInteractionsProtocolError("provider_response_invalid")
    return value


def _nonnegative_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GoogleInteractionsProtocolError("provider_response_invalid")
    return value
