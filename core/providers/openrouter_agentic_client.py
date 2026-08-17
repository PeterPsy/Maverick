"""Certified OpenRouter agentic provider client."""

from __future__ import annotations

from collections.abc import AsyncIterator
import math

from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    EphemeralCredential,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_ID,
    OpenRouterAgenticProtocolError,
)
from core.providers.openrouter_agentic_request import openrouter_chat_payload
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state
from core.providers.openrouter_agentic_stream import OpenRouterChatStreamDecoder
from core.providers.openrouter_agentic_transport import (
    OpenRouterAgenticHttpTransport,
    OpenRouterAgenticTransport,
)


class OpenRouterAgenticClient:
    """Run one exact model/upstream protocol and expose normalized events."""

    def __init__(self, *, transport: OpenRouterAgenticTransport | None = None) -> None:
        self.transport = transport or OpenRouterAgenticHttpTransport()

    @property
    def artifact_components(self) -> tuple[object, ...]:
        return (OpenRouterChatStreamDecoder, OpenRouterAgenticHttpTransport)

    async def create_response(
        self,
        request: AgenticModelRequest,
        *,
        credential: EphemeralCredential | None,
    ) -> AsyncIterator[AgenticModelEvent]:
        decoder = None
        try:
            if request.model_id != OPENROUTER_AGENTIC_MODEL_ID:
                raise OpenRouterAgenticProtocolError("provider_request_rejected")
            if credential is None:
                raise OpenRouterAgenticProtocolError("provider_authentication_failed")
            state = decode_openrouter_chat_state(request.provider_private_state)
            payload, new_messages = openrouter_chat_payload(request, state)
            decoder = OpenRouterChatStreamDecoder(
                request=request,
                state=state,
                new_messages=new_messages,
                usage_cost=openrouter_deepinfra_v4_flash_cost_microusd,
            )
            async for raw_event in self.transport.stream(payload=payload, credential=credential):
                for event in decoder.feed(raw_event):
                    yield event
            decoder.finish()
        except OpenRouterAgenticProtocolError as cause:
            ordinal = 1 if decoder is None else decoder.ordinal + 1
            yield AgenticModelEvent(
                event_type="error",
                request_id=request.request_id,
                ordinal=ordinal,
                error_code=cause.reason_code,
            )
        except Exception:
            ordinal = 1 if decoder is None else decoder.ordinal + 1
            yield AgenticModelEvent(
                event_type="error",
                request_id=request.request_id,
                ordinal=ordinal,
                error_code="provider_unavailable",
            )


def openrouter_deepinfra_v4_flash_cost_microusd(
    input_tokens: int,
    output_tokens: int,
) -> int:
    """Estimate $0.09 input / $0.18 output per million tokens."""
    return math.ceil((input_tokens * 90 + output_tokens * 180) / 1_000)


def openrouter_deepinfra_v4_flash_request_ceiling_microusd(
    request: AgenticModelRequest,
) -> int:
    """Return a conservative preflight ceiling from bytes and max output."""
    input_bytes = sum(len(block.content) for block in request.content_blocks)
    input_bytes += sum(len(result.content) for result in request.tool_results)
    input_bytes += sum(
        len(tool.name) + len(tool.description) + len(str(tool.input_schema))
        for tool in request.tool_definitions
    )
    if request.provider_private_state is not None:
        input_bytes += len(request.provider_private_state.content)
    estimated_input_tokens = max(1, math.ceil(input_bytes / 3))
    return openrouter_deepinfra_v4_flash_cost_microusd(
        estimated_input_tokens,
        request.max_output_tokens,
    )
