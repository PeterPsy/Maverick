"""Deterministic provider client for hosted-loop certification tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import asyncio

from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    AgenticProviderPrivateState,
    AgenticToolCall,
    AgenticUsage,
    EphemeralCredential,
)


class DeterministicFakeAgenticClient:
    """Emit a tool step followed by a final streamed response."""

    def __init__(
        self,
        *,
        tool_name: str | None = None,
        tool_sequence: tuple[str, ...] = (),
        tool_arguments: dict[str, object] | None = None,
        final_text: str = "fake hosted loop answer",
        stall_after_acceptance: bool = False,
        repeat_tool: bool = False,
        upstream_id: str | None = None,
        transport_error: str | None = None,
        provider_error_code: str | None = None,
        before_tool_call: Callable[[], None] | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.tool_sequence = tool_sequence
        self.tool_arguments = tool_arguments or {"value": 4}
        self.final_text = final_text
        self.stall_after_acceptance = stall_after_acceptance
        self.repeat_tool = repeat_tool
        self.upstream_id = upstream_id
        self.transport_error = transport_error
        self.provider_error_code = provider_error_code
        self.before_tool_call = before_tool_call
        self.requests: list[AgenticModelRequest] = []
        self.closed_streams = 0

    async def create_response(
        self,
        request: AgenticModelRequest,
        *,
        credential: EphemeralCredential | None,
    ) -> AsyncIterator[AgenticModelEvent]:
        self.requests.append(request)
        step = len(self.requests)
        try:
            yield AgenticModelEvent(
                "accepted",
                request.request_id,
                1,
                upstream_id=self.upstream_id,
            )
            if self.stall_after_acceptance:
                await asyncio.sleep(60)
            if self.transport_error is not None:
                raise RuntimeError(self.transport_error)
            if self.provider_error_code is not None:
                yield AgenticModelEvent(
                    "error",
                    request.request_id,
                    2,
                    error_code=self.provider_error_code,
                )
                return
            yield AgenticModelEvent(
                "provider_state",
                request.request_id,
                2,
                provider_private_state=AgenticProviderPrivateState(
                    codec_id="fake-hosted-codec",
                    codec_version="1",
                    schema_version="1",
                    content_type="application/vnd.maverick.fake-private",
                    content=f"opaque-thought-signature:{step}".encode(),
                ),
            )
            yield AgenticModelEvent(
                "usage",
                request.request_id,
                3,
                usage=AgenticUsage(input_tokens=10, output_tokens=3, estimated_cost_microusd=0),
            )
            sequence_tool = (
                self.tool_sequence[step - 1]
                if step <= len(self.tool_sequence)
                else None
            )
            selected_tool = sequence_tool or self.tool_name
            should_call_tool = selected_tool is not None and (
                bool(sequence_tool) or self.repeat_tool or not request.tool_results
            )
            if should_call_tool:
                if self.before_tool_call is not None:
                    self.before_tool_call()
                yield AgenticModelEvent(
                    "tool_call",
                    request.request_id,
                    4,
                    tool_call=AgenticToolCall(
                        provider_tool_call_id=f"fake-call-{step}",
                        provider_tool_name=selected_tool or "",
                        arguments=dict(self.tool_arguments),
                    ),
                )
            else:
                split = max(1, len(self.final_text) // 2)
                yield AgenticModelEvent(
                    "text_delta",
                    request.request_id,
                    4,
                    text=self.final_text[:split],
                )
                yield AgenticModelEvent(
                    "text_delta",
                    request.request_id,
                    5,
                    text=self.final_text[split:],
                )
                yield AgenticModelEvent(
                    "text_final",
                    request.request_id,
                    6,
                    text=self.final_text,
                )
            yield AgenticModelEvent(
                "completed",
                request.request_id,
                5 if should_call_tool else 7,
                finish_reason="tool_call" if should_call_tool else "stop",
            )
        finally:
            self.closed_streams += 1
