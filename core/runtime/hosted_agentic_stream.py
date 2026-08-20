"""Validate and normalize one hosted provider response stream."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import json
from threading import Event
from typing import Callable

from core.providers.agentic_reason_codes import normalized_agentic_provider_reason
from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelProviderClient,
    AgenticToolCall,
    EphemeralCredential,
)
from core.runtime.hosted_agentic_budget import HostedAgenticBudget
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    raise_if_hosted_cancelled,
)


@dataclass(frozen=True)
class HostedProviderStep:
    final_text: str | None
    tool_call: AgenticToolCall | None


@dataclass(frozen=True)
class HostedProviderStepEmission:
    event_type: str | None = None
    payload: dict[str, object] | None = None
    response: HostedProviderStep | None = None


async def consume_hosted_provider_step(
    *,
    client: AgenticModelProviderClient,
    request,
    credential: EphemeralCredential | None,
    budget: HostedAgenticBudget,
    cancellation: Event,
    destination_upstream_id: str | None,
    on_private_state: Callable[[AgenticModelEvent], None],
):
    """Yield safe runtime emissions and one terminal normalized step."""
    accepted = False
    completed = False
    final_text: str | None = None
    output_parts: list[str] = []
    tool_call: AgenticToolCall | None = None
    last_ordinal = 0
    try:
        stream = client.create_response(request, credential=credential)
        async for provider_event in _cancellable_events(stream, cancellation, budget):
            _validate_provider_event(provider_event, request.request_id, last_ordinal)
            last_ordinal = provider_event.ordinal
            if provider_event.event_type == "accepted":
                if accepted or completed:
                    raise HostedAgenticLoopError("provider_response_invalid")
                _validate_upstream(provider_event.upstream_id, destination_upstream_id)
                accepted = True
                payload: dict[str, object] = {"request_id": request.request_id}
                if provider_event.upstream_id:
                    payload["upstream_id"] = provider_event.upstream_id
                if provider_event.provider_response_id:
                    payload["provider_response_id"] = provider_event.provider_response_id
                yield HostedProviderStepEmission("provider.accepted", payload)
            elif provider_event.event_type == "error":
                raise HostedAgenticLoopError(
                    normalized_agentic_provider_reason(provider_event.error_code)
                )
            elif not accepted or completed:
                raise HostedAgenticLoopError("provider_response_invalid")
            elif provider_event.event_type == "text_delta":
                text = provider_event.text or ""
                budget.add_output_chunk(text)
                output_parts.append(text)
                yield HostedProviderStepEmission(
                    "runtime.output.delta",
                    {"text": text},
                )
            elif provider_event.event_type == "text_final":
                if final_text is not None:
                    raise HostedAgenticLoopError("provider_response_invalid")
                final_text = provider_event.text or ""
                if output_parts:
                    if "".join(output_parts) != final_text:
                        raise HostedAgenticLoopError("provider_response_invalid")
                else:
                    budget.add_output_chunk(final_text)
            elif provider_event.event_type == "tool_call":
                if tool_call is not None or provider_event.tool_call is None:
                    raise HostedAgenticLoopError("provider_response_invalid")
                tool_call = provider_event.tool_call
            elif provider_event.event_type == "usage":
                if provider_event.usage is None:
                    raise HostedAgenticLoopError("provider_response_invalid")
                budget.add_usage(provider_event.usage)
                yield HostedProviderStepEmission(
                    "provider.usage",
                    {
                        "input_tokens": provider_event.usage.input_tokens,
                        "output_tokens": provider_event.usage.output_tokens,
                        "estimated_cost_microusd": provider_event.usage.estimated_cost_microusd,
                    },
                )
            elif provider_event.event_type == "provider_state":
                on_private_state(provider_event)
            elif provider_event.event_type == "completed":
                completed = True
            else:
                raise HostedAgenticLoopError("provider_response_invalid")
    except HostedAgenticLoopError:
        raise
    except Exception as error:
        raise HostedAgenticLoopError("provider_response_invalid") from error
    if not accepted or not completed or (final_text is not None) == (tool_call is not None):
        raise HostedAgenticLoopError("provider_response_invalid")
    yield HostedProviderStepEmission(
        response=HostedProviderStep(final_text=final_text, tool_call=tool_call)
    )


async def _cancellable_events(stream, cancellation: Event, budget: HostedAgenticBudget):
    iterator = stream.__aiter__()
    pending = asyncio.create_task(iterator.__anext__())
    try:
        while True:
            done, _pending = await asyncio.wait({pending}, timeout=0.05)
            raise_if_hosted_cancelled(cancellation)
            budget.check_time()
            if not done:
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            yield item
            pending = asyncio.create_task(iterator.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        close = getattr(iterator, "aclose", None)
        if callable(close):
            with suppress(RuntimeError):
                await close()


def _validate_provider_event(event: AgenticModelEvent, request_id: str, last_ordinal: int) -> None:
    if event.request_id != request_id or event.ordinal <= last_ordinal:
        raise HostedAgenticLoopError("provider_response_invalid")
    if event.text is not None and len(event.text.encode("utf-8")) > 1_048_576:
        raise HostedAgenticLoopError("provider_response_invalid")
    if event.event_type != "tool_call":
        return
    call = event.tool_call
    if (
        call is None
        or not call.provider_tool_call_id
        or not call.provider_tool_name
        or not isinstance(call.arguments, dict)
    ):
        raise HostedAgenticLoopError("provider_response_invalid")
    try:
        encoded = json.dumps(call.arguments, allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as error:
        raise HostedAgenticLoopError("provider_response_invalid") from error
    if len(encoded) > 1_048_576:
        raise HostedAgenticLoopError("provider_response_invalid")


def _validate_upstream(observed: str | None, expected: str | None) -> None:
    normalized = str(observed or "").strip() or None
    if normalized != expected:
        raise HostedAgenticLoopError("provider_upstream_not_certified")
