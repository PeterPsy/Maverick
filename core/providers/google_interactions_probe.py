"""Opt-in live capability probe for Google Gemini Interactions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
    AgenticToolResult,
    EphemeralCredential,
)
from core.providers.google_agentic_profile import google_interactions_routing_constraint
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.runtime.execution_binding import canonical_digest


PROBE_TOOL_NAME = "maverick_probe_echo"
CERTIFIED_REASONING_EFFORTS = ("minimal", "low", "medium", "high")


@dataclass(frozen=True)
class GoogleInteractionsProbeResult:
    succeeded: bool
    reason_code: str
    test_run_id: str
    result_summary_digest: str
    request_count: int
    saw_streaming: bool
    saw_tool_call: bool
    saw_usage: bool
    saw_private_state: bool
    reasoning_efforts: tuple[str, ...]


async def probe_google_interactions(
    *,
    credential: EphemeralCredential,
    client: GoogleInteractionsAgenticClient | None = None,
    reasoning_efforts: tuple[str, ...] = CERTIFIED_REASONING_EFFORTS,
) -> GoogleInteractionsProbeResult:
    """Run one synthetic tool round trip per selectable effort; never return content."""
    active_client = client or GoogleInteractionsAgenticClient(state_mode="stateful")
    test_run_id = f"google-interactions-live:{uuid4()}"
    normalized_efforts = tuple(str(value).strip().lower() for value in reasoning_efforts)
    if not normalized_efforts or any(value not in CERTIFIED_REASONING_EFFORTS for value in normalized_efforts):
        return _result(test_run_id, [], "probe_reasoning_effort_invalid", 0, normalized_efforts)
    events: list = []
    request_count = 0
    for effort in normalized_efforts:
        first = [
            event
            async for event in active_client.create_response(
                _probe_request(f"{test_run_id}:{effort}:1", reasoning_effort=effort),
                credential=credential,
            )
        ]
        request_count += 1
        events.extend(first)
        error = next((event.error_code for event in first if event.event_type == "error"), None)
        call = next((event.tool_call for event in first if event.event_type == "tool_call"), None)
        private = next(
            (event.provider_private_state for event in first if event.event_type == "provider_state"),
            None,
        )
        if error or call is None or private is None or call.provider_tool_name != PROBE_TOOL_NAME:
            return _result(
                test_run_id,
                events,
                error or "probe_tool_call_missing",
                request_count,
                normalized_efforts,
            )
        second = [
            event
            async for event in active_client.create_response(
                _probe_request(
                    f"{test_run_id}:{effort}:2",
                    reasoning_effort=effort,
                    private_state=private,
                    tool_results=(
                        AgenticToolResult(
                            provider_tool_call_id=call.provider_tool_call_id,
                            provider_tool_name=call.provider_tool_name,
                            content_type="application/json",
                            content=b'{"ok":true}',
                            is_error=False,
                        ),
                    ),
                ),
                credential=credential,
            )
        ]
        request_count += 1
        events.extend(second)
        error = next((event.error_code for event in second if event.event_type == "error"), None)
        completed = any(event.event_type == "completed" for event in second)
        final = any(event.event_type == "text_final" for event in second)
        if error or not (completed and final):
            return _result(
                test_run_id,
                events,
                error or "probe_final_response_missing",
                request_count,
                normalized_efforts,
            )
    return _result(test_run_id, events, "ok", request_count, normalized_efforts)


def _probe_request(
    request_id: str,
    *,
    reasoning_effort: str,
    private_state=None,
    tool_results: tuple[AgenticToolResult, ...] = (),
) -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1",
        request_id=request_id,
        correlation_id=test_run_id_from_request(request_id),
        model_id="gemini-3.6-flash",
        reasoning_effort=reasoning_effort,
        content_blocks=(
            AgenticRequestContentBlock(
                content_block_id=f"{request_id}:user",
                role="user",
                data_class="public",
                provenance="user_input",
                trust_level="trusted_platform",
                content_type="text/plain",
                content=(
                    b"Call maverick_probe_echo exactly once with any JSON object, then after "
                    b"the function result answer with the single word OK. This is synthetic data."
                ),
            ),
        ),
        tool_definitions=(
            AgenticToolDefinition(
                name=PROBE_TOOL_NAME,
                description="Return a synthetic probe result.",
                input_schema={"type": "object", "additionalProperties": True},
            ),
        ),
        tool_results=tool_results,
        provider_private_state=private_state,
        routing_constraint=google_interactions_routing_constraint(),
        max_output_tokens=128,
    )


def _result(
    test_run_id: str,
    events: list,
    reason: str,
    request_count: int,
    reasoning_efforts: tuple[str, ...],
):
    summary = {
        "reason_code": reason,
        "request_count": request_count,
        "saw_streaming": sum(event.event_type == "text_delta" for event in events) > 0,
        "saw_tool_call": any(event.event_type == "tool_call" for event in events),
        "saw_usage": request_count > 0 and sum(event.event_type == "usage" for event in events) >= request_count,
        "saw_private_state": (
            request_count > 0
            and sum(event.event_type == "provider_state" for event in events) >= request_count
        ),
        "reasoning_efforts": reasoning_efforts,
    }
    return GoogleInteractionsProbeResult(
        succeeded=(
            reason == "ok"
            and all(summary[key] for key in ("saw_streaming", "saw_tool_call", "saw_usage", "saw_private_state"))
            and reasoning_efforts == CERTIFIED_REASONING_EFFORTS
        ),
        test_run_id=test_run_id,
        result_summary_digest=canonical_digest(summary),
        **summary,
    )


def test_run_id_from_request(request_id: str) -> str:
    return request_id.rsplit(":", 1)[0]
