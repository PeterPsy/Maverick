"""Agentic provider client for Google Gemini Interactions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
import math

import core.providers.google_interactions_models as google_interactions_models_module
import core.providers.google_interactions_request as google_interactions_request_module
import core.providers.google_interactions_state as google_interactions_state_module
import core.providers.google_interactions_stream as google_interactions_stream_module
import core.providers.google_interactions_transport as google_interactions_transport_module
from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    EphemeralCredential,
)
from core.providers.google_interactions_models import (
    GoogleInteractionStateMode,
    GoogleInteractionsProtocolError,
)
from core.providers.google_interactions_request import google_interaction_payload
from core.providers.google_interactions_state import decode_google_interaction_state
from core.providers.google_interactions_stream import GoogleInteractionStreamDecoder
from core.providers.google_interactions_transport import (
    GoogleInteractionsHttpTransport,
    GoogleInteractionsTransport,
)


GOOGLE_AGENTIC_MODEL_ID = "gemini-3.6-flash"


class GoogleInteractionsAgenticClient:
    """Preserve Google continuation privately while exposing normalized events."""

    def __init__(
        self,
        *,
        model_id: str = GOOGLE_AGENTIC_MODEL_ID,
        state_mode: GoogleInteractionStateMode = "stateful",
        transport: GoogleInteractionsTransport | None = None,
    ) -> None:
        if state_mode not in {"stateful", "stateless"}:
            raise ValueError("Unsupported Google Interactions state mode.")
        self.state_mode = state_mode
        self.model_id = str(model_id or "").strip()
        if not self.model_id:
            raise ValueError("Google Interactions model id is required.")
        self.transport = transport or GoogleInteractionsHttpTransport()

    @property
    def artifact_components(self) -> tuple[object, ...]:
        """Expose codec and transport modules included in capability evidence."""
        return (
            google_interactions_models_module,
            google_interactions_request_module,
            google_interactions_state_module,
            google_interactions_stream_module,
            google_interactions_transport_module,
        )

    async def create_response(
        self,
        request: AgenticModelRequest,
        *,
        credential: EphemeralCredential | None,
    ) -> AsyncIterator[AgenticModelEvent]:
        decoder = None
        failure: GoogleInteractionsProtocolError | None = None
        try:
            if request.model_id != self.model_id:
                raise GoogleInteractionsProtocolError("provider_request_rejected")
            if credential is None:
                raise GoogleInteractionsProtocolError("provider_authentication_failed")
            state = decode_google_interaction_state(
                request.provider_private_state,
                default_mode=self.state_mode,
            )
            payload, new_input = google_interaction_payload(request, state)
            decoder = GoogleInteractionStreamDecoder(
                request=request,
                state=state,
                new_input=new_input,
                usage_cost=google_36_flash_cost_microusd,
            )
            async for raw_event in self.transport.stream(payload=payload, credential=credential):
                if failure is not None:
                    for event in decoder.failure_telemetry(raw_event):
                        yield event
                    continue
                try:
                    events = decoder.feed(raw_event)
                except GoogleInteractionsProtocolError as error:
                    failure = error
                    for event in decoder.failure_telemetry(raw_event):
                        yield event
                    continue
                terminal_error = False
                for event in events:
                    if event.provider_private_state is not None:
                        event = replace(
                            event,
                            provider_private_state=replace(
                                event.provider_private_state,
                                provider_request_id=request.request_id,
                                turn_generation=request.correlation_id,
                            ),
                        )
                    yield event
                    terminal_error = terminal_error or event.event_type == "error"
                if terminal_error:
                    return
            if failure is not None:
                yield AgenticModelEvent(
                    event_type="error",
                    request_id=request.request_id,
                    ordinal=decoder.ordinal + 1,
                    error_code=failure.reason_code,
                )
                return
            decoder.finish()
        except GoogleInteractionsProtocolError as error:
            ordinal = 1 if decoder is None else decoder.ordinal + 1
            yield AgenticModelEvent(
                event_type="error",
                request_id=request.request_id,
                ordinal=ordinal,
                error_code=error.reason_code,
            )
        except Exception:
            ordinal = 1 if decoder is None else decoder.ordinal + 1
            yield AgenticModelEvent(
                event_type="error",
                request_id=request.request_id,
                ordinal=ordinal,
                error_code=(
                    failure.reason_code
                    if failure is not None
                    else "provider_unavailable"
                ),
            )


def google_36_flash_cost_microusd(input_tokens: int, output_tokens: int) -> int:
    """Estimate public list-price cost: $1.50 input / $7.50 output per 1M tokens."""
    return math.ceil((input_tokens * 1_500 + output_tokens * 7_500) / 1_000)


def google_36_flash_request_ceiling_microusd(request: AgenticModelRequest) -> int:
    """Return a conservative preflight ceiling from bytes plus max output tokens."""
    input_bytes = sum(len(block.content) for block in request.content_blocks)
    input_bytes += sum(len(result.content) for result in request.tool_results)
    input_bytes += sum(
        len(tool.name) + len(tool.description) + len(str(tool.input_schema))
        for tool in request.tool_definitions
    )
    if request.provider_private_state is not None:
        input_bytes += len(request.provider_private_state.content)
    estimated_input_tokens = max(1, math.ceil(input_bytes / 3))
    return google_36_flash_cost_microusd(
        estimated_input_tokens,
        request.max_output_tokens,
    )
