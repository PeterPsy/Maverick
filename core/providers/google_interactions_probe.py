"""Opt-in live capability probe for Google Gemini Interactions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
import tempfile
from uuid import uuid4

from core.providers.agentic_filesystem_probe import (
    AgenticFilesystemListProbe,
    FILESYSTEM_LIST_PROBE_TOOL_NAME,
)
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
    EphemeralCredential,
)
from core.providers.google_agentic_profile import (
    GOOGLE_CERTIFIED_REASONING_EFFORTS,
    google_interactions_routing_constraint,
)
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.runtime.execution_binding import canonical_digest


PROBE_TOOL_NAME = FILESYSTEM_LIST_PROBE_TOOL_NAME
CERTIFIED_REASONING_EFFORTS = GOOGLE_CERTIFIED_REASONING_EFFORTS
CERTIFICATION_PROBE_MAX_OUTPUT_TOKENS = 2_048
CERTIFICATION_PROBE_TOOL_ROUNDS = 2


@dataclass(frozen=True)
class GoogleInteractionsProbeResult:
    succeeded: bool
    reason_code: str
    test_run_id: str
    result_summary_digest: str
    request_count: int
    saw_streaming: bool
    saw_tool_call: bool
    saw_filesystem_list: bool
    saw_usage: bool
    saw_private_state: bool
    reasoning_efforts: tuple[str, ...]


async def probe_google_interactions(
    *,
    credential: EphemeralCredential,
    client: GoogleInteractionsAgenticClient | None = None,
    reasoning_efforts: tuple[str, ...] = CERTIFIED_REASONING_EFFORTS,
    request_interval_seconds: float = 1.0,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> GoogleInteractionsProbeResult:
    """Run a paced two-tool continuation round trip per certified effort."""
    active_client = client or GoogleInteractionsAgenticClient(state_mode="stateful")
    test_run_id = f"google-interactions-live:{uuid4()}"
    normalized_efforts = tuple(str(value).strip().lower() for value in reasoning_efforts)
    if not normalized_efforts or any(
        value not in CERTIFIED_REASONING_EFFORTS
        for value in normalized_efforts
    ):
        return _result(
            test_run_id,
            [],
            "probe_reasoning_effort_invalid",
            0,
            normalized_efforts,
            0,
        )
    events: list = []
    request_count = 0
    filesystem_result_count = 0
    with tempfile.TemporaryDirectory(prefix="maverick-google-agentic-probe-") as temp_dir:
        filesystem_probe = AgenticFilesystemListProbe.create(Path(temp_dir))
        for effort in normalized_efforts:
            private = None
            tool_results = []
            for tool_round in range(1, CERTIFICATION_PROBE_TOOL_ROUNDS + 1):
                await _pace(request_count, request_interval_seconds, sleep)
                response = [
                    event
                    async for event in active_client.create_response(
                        _probe_request(
                            f"{test_run_id}:{effort}:{tool_round}",
                            reasoning_effort=effort,
                            tool_definition=filesystem_probe.definition,
                            private_state=private,
                            tool_results=tuple(tool_results),
                        ),
                        credential=credential,
                    )
                ]
                request_count += 1
                events.extend(response)
                error = next(
                    (
                        event.error_code
                        for event in response
                        if event.event_type == "error"
                    ),
                    None,
                )
                call = next(
                    (
                        event.tool_call
                        for event in response
                        if event.event_type == "tool_call"
                    ),
                    None,
                )
                private = next(
                    (
                        event.provider_private_state
                        for event in response
                        if event.event_type == "provider_state"
                    ),
                    None,
                )
                if (
                    error
                    or call is None
                    or private is None
                    or call.provider_tool_name != PROBE_TOOL_NAME
                ):
                    return _result(
                        test_run_id,
                        events,
                        error or "probe_tool_call_missing",
                        request_count,
                        normalized_efforts,
                        filesystem_result_count,
                    )
                try:
                    tool_results.append(filesystem_probe.execute(call))
                except (OSError, TypeError, ValueError, RuntimeError):
                    return _result(
                        test_run_id,
                        events,
                        "probe_filesystem_list_failed",
                        request_count,
                        normalized_efforts,
                        filesystem_result_count,
                    )
                filesystem_result_count += 1
            await _pace(request_count, request_interval_seconds, sleep)
            final_response = [
                event
                async for event in active_client.create_response(
                    _probe_request(
                        f"{test_run_id}:{effort}:{CERTIFICATION_PROBE_TOOL_ROUNDS + 1}",
                        reasoning_effort=effort,
                        tool_definition=filesystem_probe.definition,
                        private_state=private,
                        tool_results=tuple(tool_results),
                    ),
                    credential=credential,
                )
            ]
            request_count += 1
            events.extend(final_response)
            error = next(
                (
                    event.error_code
                    for event in final_response
                    if event.event_type == "error"
                ),
                None,
            )
            completed = any(
                event.event_type == "completed" for event in final_response
            )
            final = any(event.event_type == "text_final" for event in final_response)
            if error or not (completed and final):
                return _result(
                    test_run_id, events, error or "probe_final_response_missing", request_count,
                    normalized_efforts, filesystem_result_count,
                )
    return _result(
        test_run_id, events, "ok", request_count, normalized_efforts, filesystem_result_count
    )


def _probe_request(
    request_id: str,
    *,
    reasoning_effort: str,
    tool_definition: AgenticToolDefinition,
    private_state=None,
    tool_results=(),
) -> AgenticModelRequest:
    pairing = private_state is not None and bool(tool_results)
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
                    f"Call {PROBE_TOOL_NAME} exactly twice in two sequential function-call "
                    "steps, both times with path '.', max_depth 1, and max_results 10. "
                    "Do not answer after the first result. After the second result answer "
                    "with the single word OK. "
                    "This isolated directory contains synthetic data only."
                ).encode("utf-8"),
            ),
        ),
        tool_definitions=(tool_definition,),
        tool_results=tool_results,
        provider_private_state=private_state,
        routing_constraint=google_interactions_routing_constraint(),
        # Thinking tokens consume the same output budget. A 128-token probe can
        # terminate as `incomplete` at medium/high before the declared tool is
        # reached, which tests the budget rather than the function-call contract.
        max_output_tokens=CERTIFICATION_PROBE_MAX_OUTPUT_TOKENS,
        pairing_source_journal_id=(
            f"certification-probe:{private_state.provider_request_id}"
            if pairing
            else None
        ),
        pairing_source_turn_id=(
            private_state.turn_generation if pairing else None
        ),
        pairing_source_request_id=(
            private_state.provider_request_id if pairing else None
        ),
    )


def _result(
    test_run_id: str,
    events: list,
    reason: str,
    request_count: int,
    reasoning_efforts: tuple[str, ...],
    filesystem_result_count: int,
):
    summary = {
        "reason_code": reason,
        "request_count": request_count,
        "saw_streaming": sum(event.event_type == "text_delta" for event in events) > 0,
        "saw_tool_call": any(event.event_type == "tool_call" for event in events),
        "saw_filesystem_list": filesystem_result_count == (
            CERTIFICATION_PROBE_TOOL_ROUNDS * len(reasoning_efforts)
        ),
        "saw_usage": (
            request_count > 0
            and sum(event.event_type == "usage" for event in events) >= request_count
        ),
        "saw_private_state": (
            request_count > 0
            and sum(event.event_type == "provider_state" for event in events) >= request_count
        ),
        "reasoning_efforts": reasoning_efforts,
    }
    return GoogleInteractionsProbeResult(
        succeeded=(
            reason == "ok"
            and all(
                summary[key]
                for key in (
                    "saw_streaming",
                    "saw_tool_call",
                    "saw_filesystem_list",
                    "saw_usage",
                    "saw_private_state",
                )
            )
            and reasoning_efforts == CERTIFIED_REASONING_EFFORTS
        ),
        test_run_id=test_run_id,
        result_summary_digest=canonical_digest(summary),
        **summary,
    )


def test_run_id_from_request(request_id: str) -> str:
    return request_id.rsplit(":", 1)[0]


async def _pace(
    request_count: int,
    interval_seconds: float,
    sleep: Callable[[float], Awaitable[object]],
) -> None:
    if request_count and interval_seconds > 0:
        await sleep(interval_seconds)
