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


async def probe_google_interactions(
    *,
    credential: EphemeralCredential,
    client: GoogleInteractionsAgenticClient | None = None,
) -> GoogleInteractionsProbeResult:
    """Run a synthetic two-request tool round trip; never return model content."""
    active_client = client or GoogleInteractionsAgenticClient(state_mode="stateful")
    test_run_id = f"google-interactions-live:{uuid4()}"
    first = [
        event
        async for event in active_client.create_response(
            _probe_request(f"{test_run_id}:1"),
            credential=credential,
        )
    ]
    error = next((event.error_code for event in first if event.event_type == "error"), None)
    call = next((event.tool_call for event in first if event.event_type == "tool_call"), None)
    private = next(
        (event.provider_private_state for event in first if event.event_type == "provider_state"),
        None,
    )
    if error or call is None or private is None or call.provider_tool_name != PROBE_TOOL_NAME:
        return _result(test_run_id, first, (), error or "probe_tool_call_missing")
    second = [
        event
        async for event in active_client.create_response(
            _probe_request(
                f"{test_run_id}:2",
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
    error = next((event.error_code for event in second if event.event_type == "error"), None)
    completed = any(event.event_type == "completed" for event in second)
    final = any(event.event_type == "text_final" for event in second)
    reason = error or ("ok" if completed and final else "probe_final_response_missing")
    return _result(test_run_id, first, second, reason)


def _probe_request(
    request_id: str,
    *,
    private_state=None,
    tool_results: tuple[AgenticToolResult, ...] = (),
) -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1",
        request_id=request_id,
        correlation_id=test_run_id_from_request(request_id),
        model_id="gemini-3.6-flash",
        reasoning_effort="minimal",
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


def _result(test_run_id: str, first: list, second: tuple | list, reason: str):
    events = [*first, *second]
    summary = {
        "reason_code": reason,
        "request_count": 1 + bool(second),
        "saw_streaming": sum(event.event_type == "text_delta" for event in events) > 0,
        "saw_tool_call": any(event.event_type == "tool_call" for event in events),
        "saw_usage": sum(event.event_type == "usage" for event in events) >= 1 + bool(second),
        "saw_private_state": sum(event.event_type == "provider_state" for event in events)
        >= 1 + bool(second),
    }
    return GoogleInteractionsProbeResult(
        succeeded=reason == "ok" and all(summary.values()),
        test_run_id=test_run_id,
        result_summary_digest=canonical_digest(summary),
        **summary,
    )


def test_run_id_from_request(request_id: str) -> str:
    return request_id.rsplit(":", 1)[0]
