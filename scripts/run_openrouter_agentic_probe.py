#!/usr/bin/env python3
"""Operator-only synthetic OpenRouter live probe used by certification."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.providers.agentic_filesystem_probe import AgenticFilesystemListProbe
from core.providers.agentic_probe_validation import validate_probe_response
from core.providers.certification_target import builtin_api_certification_target
from core.providers.certification_probe_budget import CertificationProbeTransport
from core.providers.agentic_protocol import (
    AgenticModelRequest, AgenticRequestContentBlock, AgenticToolDefinition,
    EphemeralCredential, HOSTED_FINALIZATION_INSTRUCTION,
)
from core.providers.openrouter_agentic_catalog import preflight_openrouter_agentic_catalog
from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from core.providers.openrouter_agentic_transport import OpenRouterAgenticHttpTransport
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_ID, OPENROUTER_AGENTIC_MODEL_REVISION,
)
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_CERTIFIED_REASONING_EFFORTS,
    openrouter_agentic_routing_constraint,
)


CERTIFIED_REASONING_EFFORTS = OPENROUTER_CERTIFIED_REASONING_EFFORTS
TOOL_CALLS_PER_EFFORT = 3
REQUESTS_PER_EFFORT = TOOL_CALLS_PER_EFFORT + 1


async def _main() -> int:
    value = os.environ.get("MAVERICK_OPENROUTER_CERTIFICATION_API_KEY", "").strip()
    if not value:
        return 2
    credential = EphemeralCredential(value)
    interval = _request_interval_seconds()
    client = OpenRouterAgenticClient(transport=CertificationProbeTransport(
        OpenRouterAgenticHttpTransport(), provider_id="openrouter",
    ))
    events = []
    request_count = 0
    filesystem_result_count = 0
    with tempfile.TemporaryDirectory(prefix="maverick-openrouter-agentic-probe-") as temp_dir:
        filesystem_probe = AgenticFilesystemListProbe.create(Path(temp_dir))
        catalog_request = _request(
            request_id="openrouter-live-synthetic-probe:catalog",
            reasoning_effort="high",
            tool_definition=filesystem_probe.definition,
            max_output_tokens=16_384,
        )
        try:
            catalog = await asyncio.to_thread(
                preflight_openrouter_agentic_catalog,
                catalog_request,
                credential=credential,
            )
        except Exception as error:
            print(json.dumps({
                "reason_code": getattr(error, "reason_code", "provider_unavailable"),
                "request_count": 0,
                "succeeded": False,
            }, sort_keys=True))
            return 1
        for effort in CERTIFIED_REASONING_EFFORTS:
            private = None
            tool_results = []
            for tool_round in range(1, TOOL_CALLS_PER_EFFORT + 1):
                await _pace(request_count, interval)
                response = [event async for event in client.create_response(
                    _request(
                        request_id=(
                            f"openrouter-live-synthetic-probe:{effort}:{tool_round}"
                        ),
                        reasoning_effort=effort,
                        tool_definition=filesystem_probe.definition,
                        private_state=private,
                        tool_results=tuple(tool_results),
                    ),
                    credential=credential,
                )]
                request_count += 1
                events.extend(response)
                call = next((
                    event.tool_call for event in response
                    if event.event_type == "tool_call"
                ), None)
                private = next((
                    event.provider_private_state for event in response
                    if event.event_type == "provider_state"
                ), None)
                if (
                    call is None
                    or private is None
                    or not validate_probe_response(response, final=False)
                ):
                    return _finish(
                        events, request_count, filesystem_result_count, catalog,
                        failure=True,
                    )
                try:
                    tool_results.append(filesystem_probe.execute(call))
                except (OSError, TypeError, ValueError, RuntimeError):
                    return _finish(
                        events, request_count, filesystem_result_count, catalog,
                        failure=True,
                    )
                filesystem_result_count += 1
            await _pace(request_count, interval)
            final = [event async for event in client.create_response(
                _request(
                    request_id=(
                        f"openrouter-live-synthetic-probe:{effort}:"
                        f"{REQUESTS_PER_EFFORT}"
                    ),
                    reasoning_effort=effort,
                    tool_definition=filesystem_probe.definition,
                    private_state=private,
                    tool_results=tuple(tool_results),
                    finalize=True,
                ),
                credential=credential,
            )]
            request_count += 1
            events.extend(final)
            if not validate_probe_response(final, final=True):
                return _finish(events, request_count, filesystem_result_count, catalog, failure=True)
    return _finish(events, request_count, filesystem_result_count, catalog)


def _request(
    *,
    request_id: str,
    reasoning_effort: str,
    tool_definition: AgenticToolDefinition,
    private_state=None,
    tool_results=(),
    max_output_tokens: int = 2_048,
    finalize: bool = False,
) -> AgenticModelRequest:
    pairing = private_state is not None and bool(tool_results)
    return AgenticModelRequest(
        schema_version="1", request_id=request_id,
        correlation_id=request_id.rsplit(":", 1)[0],
        model_id=OPENROUTER_AGENTIC_MODEL_ID, reasoning_effort=reasoning_effort,
        model_revision=OPENROUTER_AGENTIC_MODEL_REVISION,
        model_revision_policy="provider_alias",
        content_blocks=(
            AgenticRequestContentBlock(
                content_block_id="synthetic-user", role="user", data_class="public",
                provenance="user_input", trust_level="trusted_platform",
                content_type="text/plain",
                content=(
                    f"Call {tool_definition.name} exactly three times total, one call per "
                    "response, with path '.', max_depth 1, and max_results 10. After each "
                    "of the first two results, call it once again. After the third result, "
                    "answer OK. Synthetic data only."
                ).encode("utf-8"),
            ),
            *(
                (
                    AgenticRequestContentBlock(
                        content_block_id="synthetic-finalization",
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
        tool_definitions=() if finalize else (tool_definition,), tool_results=tool_results,
        provider_private_state=private_state,
        routing_constraint=openrouter_agentic_routing_constraint(),
        max_output_tokens=max_output_tokens,
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


async def _pace(request_count: int, interval_seconds: float) -> None:
    if request_count and interval_seconds > 0:
        await asyncio.sleep(interval_seconds)


def _request_interval_seconds() -> float:
    try:
        value = float(os.environ.get("MAVERICK_CERTIFICATION_PROBE_INTERVAL_SECONDS", "1"))
    except ValueError:
        return 1.0
    return max(0.0, min(value, 30.0))


def _finish(events, request_count: int, filesystem_result_count: int, catalog, *, failure=False) -> int:
    succeeded = (
        not failure
        and request_count == REQUESTS_PER_EFFORT * len(CERTIFIED_REASONING_EFFORTS)
        and filesystem_result_count == (
            TOOL_CALLS_PER_EFFORT * len(CERTIFIED_REASONING_EFFORTS)
        )
        and sum(event.event_type == "usage" for event in events) >= request_count
        and sum(event.event_type == "provider_state" for event in events) >= request_count
        and not any(event.event_type == "error" for event in events)
        and catalog.context_length >= 16_384
        and catalog.max_completion_tokens >= 16_384
    )
    print(json.dumps({
        "target_digest": builtin_api_certification_target("openrouter"),
        "run_nonce": os.environ.get("MAVERICK_CERTIFICATION_RUN_NONCE", ""),
        "catalog_snapshot_digest": catalog.catalog_snapshot_digest,
        "catalog_model_record_digest": catalog.model_catalog_record_digest,
        "catalog_zdr_record_digest": catalog.zdr_catalog_record_digest,
        "context_length": catalog.context_length,
        "filesystem_result_count": filesystem_result_count,
        "max_completion_tokens": catalog.max_completion_tokens,
        "reasoning_efforts": CERTIFIED_REASONING_EFFORTS,
        "request_count": request_count,
        "succeeded": succeeded,
        "supports_tool_choice_none": catalog.supports_tool_choice_none,
        "finalization_mode": "omit_tools_and_choice",
        "upstream_id": catalog.upstream_id,
    }, sort_keys=True))
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
