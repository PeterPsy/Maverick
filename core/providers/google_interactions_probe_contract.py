"""Exact synthetic Google probe request and redaction-safe result contract."""

from dataclasses import dataclass

from core.providers.agentic_filesystem_probe import FILESYSTEM_LIST_PROBE_TOOL_NAME
from core.providers.agentic_protocol import (
    AgenticModelRequest, AgenticRequestContentBlock, AgenticToolDefinition,
    HOSTED_FINALIZATION_INSTRUCTION,
)
from core.providers.google_interactions_catalog import GoogleInteractionsCatalogSnapshot
from core.providers.google_interactions_client import GOOGLE_AGENTIC_MODEL_REVISION
from core.providers.google_agentic_profile import GOOGLE_CERTIFIED_REASONING_EFFORTS, google_interactions_routing_constraint
from core.providers.google_interactions_probe_catalog import observed_google_probe_target
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
    target_digest: str
    catalog_snapshots: tuple[GoogleInteractionsCatalogSnapshot, ...]


def google_probe_request(
    request_id: str,
    *,
    reasoning_effort: str,
    tool_definition: AgenticToolDefinition,
    private_state=None,
    tool_results=(),
    finalize: bool = False,
) -> AgenticModelRequest:
    pairing = private_state is not None and bool(tool_results)
    return AgenticModelRequest(
        schema_version="1",
        request_id=request_id,
        correlation_id=request_id.rsplit(":", 1)[0],
        model_id="gemini-3.6-flash",
        model_revision=GOOGLE_AGENTIC_MODEL_REVISION,
        model_revision_policy="exact",
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
            *(
                (
                    AgenticRequestContentBlock(
                        content_block_id=f"{request_id}:finalization",
                        role="system",
                        data_class="public",
                        provenance="finalization_instruction",
                        trust_level="trusted_platform",
                        content_type="text/plain",
                        content=HOSTED_FINALIZATION_INSTRUCTION.encode("utf-8"),
                    ),
                )
                if finalize
                else ()
            ),
        ),
        tool_definitions=() if finalize else (tool_definition,),
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
        request_phase="finalization" if finalize else "exploration",
    )


def google_probe_result(
    test_run_id: str,
    events: list,
    reason: str,
    request_count: int,
    reasoning_efforts: tuple[str, ...],
    filesystem_result_count: int,
    catalog_snapshots: tuple[GoogleInteractionsCatalogSnapshot, ...] = (),
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
        "catalog_snapshots": catalog_snapshots,
    }
    return GoogleInteractionsProbeResult(
        succeeded=(
            reason == "ok"
            and request_count == len(catalog_snapshots) == (CERTIFICATION_PROBE_TOOL_ROUNDS + 1) * len(reasoning_efforts)
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
        target_digest=(observed_google_probe_target(catalog_snapshots[0]) if catalog_snapshots else ""),
        result_summary_digest=canonical_digest(summary),
        **summary,
    )

