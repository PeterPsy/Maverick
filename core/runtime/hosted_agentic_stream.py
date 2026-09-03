"""Validate and normalize one hosted provider response stream."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import json
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
from core.runtime.hosted_agentic_transport import HostedTransportAuthorization
from core.runtime.runtime_cancellation import RuntimeCancellationSignal


@dataclass(frozen=True)
class HostedProviderStep:
    final_text: str | None
    tool_calls: tuple[AgenticToolCall, ...]

    @property
    def tool_call(self) -> AgenticToolCall | None:
        """Compatibility projection for sequential callers."""
        return self.tool_calls[0] if len(self.tool_calls) == 1 else None


@dataclass(frozen=True)
class HostedProviderStepEmission:
    event_type: str | None = None
    payload: dict[str, object] | None = None
    response: HostedProviderStep | None = None


def open_hosted_provider_response_stream(
    *,
    client: AgenticModelProviderClient,
    request,
    credential: EphemeralCredential | None,
):
    """Create the lazy provider stream; no remote byte may move at this call."""
    return client.create_response(request, credential=credential)


async def consume_hosted_provider_step(
    *,
    client: AgenticModelProviderClient,
    request,
    budget: HostedAgenticBudget,
    cancellation: RuntimeCancellationSignal,
    destination_upstream_id: str | None,
    authorize_transport: Callable[[], HostedTransportAuthorization],
    revalidate_transport: Callable[[], object],
    on_accepted: Callable[[AgenticModelEvent], None] | None = None,
    on_tool_call: Callable[[AgenticModelEvent], dict[str, object]] | None = None,
    on_private_state: Callable[[AgenticModelEvent], None] | None = None,
    on_usage: Callable[[AgenticModelEvent], None] | None = None,
):
    """Yield safe runtime emissions and one terminal normalized step."""
    accepted = False
    completed = False
    final_text: str | None = None
    output_parts: list[str] = []
    tool_calls: list[AgenticToolCall] = []
    usage_seen = False
    last_ordinal = 0
    try:
        async for provider_event in _cancellable_provider_events(
            client=client,
            request=request,
            cancellation=cancellation,
            budget=budget,
            authorize_transport=authorize_transport,
            revalidate_transport=revalidate_transport,
        ):
            _validate_provider_event(provider_event, request.request_id, last_ordinal)
            last_ordinal = provider_event.ordinal
            if provider_event.event_type == "accepted":
                if accepted or completed:
                    raise HostedAgenticLoopError("provider_response_invalid")
                _validate_upstream(provider_event.upstream_id, destination_upstream_id)
                accepted = True
                if on_accepted is not None:
                    on_accepted(provider_event)
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
                if provider_event.tool_call is None:
                    raise HostedAgenticLoopError("provider_response_invalid")
                proposed_payload = (
                    on_tool_call(provider_event)
                    if on_tool_call is not None
                    else {
                        "provider_tool_call_id": provider_event.tool_call.provider_tool_call_id,
                        "provider_tool_name": provider_event.tool_call.provider_tool_name,
                    }
                )
                tool_calls.append(provider_event.tool_call)
                yield HostedProviderStepEmission(
                    "runtime.tool_call.proposed",
                    proposed_payload,
                )
            elif provider_event.event_type == "usage":
                if usage_seen:
                    raise HostedAgenticLoopError("provider_response_invalid")
                if provider_event.usage is None:
                    raise HostedAgenticLoopError("provider_response_invalid")
                if on_usage is not None:
                    on_usage(provider_event)
                budget.add_usage(provider_event.usage)
                usage_seen = True
                yield HostedProviderStepEmission(
                    "provider.usage",
                    {
                        "usage_id": f"{request.request_id}:{provider_event.ordinal}",
                        "request_id": request.request_id,
                        "input_tokens": provider_event.usage.input_tokens,
                        "output_tokens": provider_event.usage.output_tokens,
                        "total_tokens": provider_event.usage.input_tokens + provider_event.usage.output_tokens,
                        "estimated_cost_microusd": provider_event.usage.estimated_cost_microusd,
                    },
                )
            elif provider_event.event_type == "provider_state":
                if on_private_state is not None:
                    on_private_state(provider_event)
            elif provider_event.event_type == "completed":
                completed = True
            else:
                raise HostedAgenticLoopError("provider_response_invalid")
    except HostedAgenticLoopError:
        raise
    except Exception as error:
        raise HostedAgenticLoopError("provider_response_invalid") from error
    if not accepted or not completed or (final_text is not None) == bool(tool_calls):
        raise HostedAgenticLoopError("provider_response_invalid")
    yield HostedProviderStepEmission(
        response=HostedProviderStep(final_text=final_text, tool_calls=tuple(tool_calls))
    )


async def _cancellable_events(
    stream,
    cancellation: RuntimeCancellationSignal,
    budget: HostedAgenticBudget,
    *,
    before_transport: Callable[[], object],
):
    """Retain the guarded iterator helper for already-constructed test streams."""
    iterator = stream.__aiter__()
    async for item in _drive_cancellable_events(
        iterator_holder=[iterator],
        initial_next=_next_provider_event(
            iterator,
            before_transport=before_transport,
        ),
        cancellation=cancellation,
        budget=budget,
        before_transport=before_transport,
    ):
        yield item


async def _cancellable_provider_events(
    *,
    client,
    request,
    cancellation: RuntimeCancellationSignal,
    budget: HostedAgenticBudget,
    authorize_transport: Callable[[], HostedTransportAuthorization],
    revalidate_transport: Callable[[], object],
):
    iterator_holder: list[object] = []
    async for item in _drive_cancellable_events(
        iterator_holder=iterator_holder,
        initial_next=_open_and_next_provider_event(
            client=client,
            request=request,
            iterator_holder=iterator_holder,
            authorize_transport=authorize_transport,
        ),
        cancellation=cancellation,
        budget=budget,
        before_transport=revalidate_transport,
    ):
        yield item


async def _drive_cancellable_events(
    *,
    iterator_holder: list[object],
    initial_next,
    cancellation: RuntimeCancellationSignal,
    budget: HostedAgenticBudget,
    before_transport: Callable[[], object],
):
    pending = asyncio.create_task(initial_next)
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
            iterator = iterator_holder[0]
            pending = asyncio.create_task(
                _next_provider_event(
                    iterator,
                    before_transport=before_transport,
                )
            )
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        if iterator_holder:
            close = getattr(iterator_holder[0], "aclose", None)
            if callable(close):
                with suppress(RuntimeError):
                    await close()


async def _open_and_next_provider_event(
    *,
    client,
    request,
    iterator_holder: list[object],
    authorize_transport: Callable[[], HostedTransportAuthorization],
) -> object:
    """Authorize, bind the fresh credential, and advance without yielding."""
    authorization = authorize_transport()
    if not isinstance(authorization, HostedTransportAuthorization):
        raise HostedAgenticLoopError("runtime_authority_unavailable")
    stream = open_hosted_provider_response_stream(
        client=client,
        request=request,
        credential=authorization.credential,
    )
    iterator = stream.__aiter__()
    iterator_holder.append(iterator)
    return await iterator.__anext__()


async def _next_provider_event(
    iterator,
    *,
    before_transport: Callable[[], object],
) -> object:
    """Run the live guard in the task that advances the lazy client stream."""
    before_transport()
    return await iterator.__anext__()


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
        or not isinstance(call.call_index, int)
        or isinstance(call.call_index, bool)
        or call.call_index < 0
    ):
        raise HostedAgenticLoopError("provider_response_invalid")
    if call.arguments is not None:
        if not isinstance(call.arguments, dict) or call.arguments_raw is not None:
            raise HostedAgenticLoopError("provider_response_invalid")
        try:
            encoded = json.dumps(
                call.arguments,
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError):
            encoded = repr(call.arguments).encode("utf-8", errors="replace")
    elif not isinstance(call.arguments_raw, bytes) or not call.arguments_raw:
        raise HostedAgenticLoopError("provider_response_invalid")
    else:
        encoded = call.arguments_raw
    if len(encoded) > 1_048_576:
        raise HostedAgenticLoopError("provider_response_invalid")


def _validate_upstream(observed: str | None, expected: str | None) -> None:
    normalized = str(observed or "").strip() or None
    if normalized != expected:
        raise HostedAgenticLoopError("provider_upstream_not_certified")
