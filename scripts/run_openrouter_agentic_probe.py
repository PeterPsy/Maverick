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
from core.providers.agentic_protocol import (
    AgenticModelRequest, AgenticRequestContentBlock, AgenticToolDefinition,
    EphemeralCredential,
)
from core.providers.openrouter_agentic_catalog import preflight_openrouter_agentic_catalog
from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from core.providers.openrouter_agentic_models import OPENROUTER_AGENTIC_MODEL_ID
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_CERTIFIED_REASONING_EFFORTS,
    openrouter_agentic_routing_constraint,
)


CERTIFIED_REASONING_EFFORTS = OPENROUTER_CERTIFIED_REASONING_EFFORTS


async def _main() -> int:
    value = os.environ.get("MAVERICK_OPENROUTER_CERTIFICATION_API_KEY", "").strip()
    if not value:
        return 2
    credential = EphemeralCredential(value)
    interval = _request_interval_seconds()
    client = OpenRouterAgenticClient()
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
            await _pace(request_count, interval)
            first = [event async for event in client.create_response(
                _request(
                    request_id=f"openrouter-live-synthetic-probe:{effort}:1",
                    reasoning_effort=effort,
                    tool_definition=filesystem_probe.definition,
                ),
                credential=credential,
            )]
            request_count += 1
            events.extend(first)
            call = next((event.tool_call for event in first if event.event_type == "tool_call"), None)
            private = next((
                event.provider_private_state for event in first
                if event.event_type == "provider_state"
            ), None)
            if call is None or private is None or any(event.event_type == "error" for event in first):
                return _finish(events, request_count, filesystem_result_count, catalog)
            try:
                tool_result = filesystem_probe.execute(call)
            except (OSError, TypeError, ValueError, RuntimeError):
                return _finish(events, request_count, filesystem_result_count, catalog)
            filesystem_result_count += 1
            await _pace(request_count, interval)
            second = [event async for event in client.create_response(
                _request(
                    request_id=f"openrouter-live-synthetic-probe:{effort}:2",
                    reasoning_effort=effort,
                    tool_definition=filesystem_probe.definition,
                    private_state=private,
                    tool_results=(tool_result,),
                ),
                credential=credential,
            )]
            request_count += 1
            events.extend(second)
            if (
                not any(event.event_type == "text_final" for event in second)
                or not any(event.event_type == "completed" for event in second)
                or any(event.event_type == "error" for event in second)
            ):
                return _finish(events, request_count, filesystem_result_count, catalog)
    return _finish(events, request_count, filesystem_result_count, catalog)


def _request(
    *,
    request_id: str,
    reasoning_effort: str,
    tool_definition: AgenticToolDefinition,
    private_state=None,
    tool_results=(),
    max_output_tokens: int = 128,
) -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1", request_id=request_id,
        correlation_id=request_id.rsplit(":", 1)[0],
        model_id=OPENROUTER_AGENTIC_MODEL_ID, reasoning_effort=reasoning_effort,
        content_blocks=(AgenticRequestContentBlock(
            content_block_id="synthetic-user", role="user", data_class="public",
            provenance="user_input", trust_level="trusted_platform",
            content_type="text/plain",
            content=(
                f"Call {tool_definition.name} exactly once with path '.', max_depth 1, and "
                "max_results 10. Then answer OK. Synthetic data only."
            ).encode("utf-8"),
        ),),
        tool_definitions=(tool_definition,), tool_results=tool_results,
        provider_private_state=private_state,
        routing_constraint=openrouter_agentic_routing_constraint(),
        max_output_tokens=max_output_tokens,
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


def _finish(events, request_count: int, filesystem_result_count: int, catalog) -> int:
    succeeded = (
        request_count == 2 * len(CERTIFIED_REASONING_EFFORTS)
        and filesystem_result_count == len(CERTIFIED_REASONING_EFFORTS)
        and sum(event.event_type == "usage" for event in events) >= request_count
        and sum(event.event_type == "provider_state" for event in events) >= request_count
        and not any(event.event_type == "error" for event in events)
    )
    print(json.dumps({
        "catalog_model_record_digest": catalog.model_catalog_record_digest,
        "catalog_zdr_record_digest": catalog.zdr_catalog_record_digest,
        "filesystem_result_count": filesystem_result_count,
        "reasoning_efforts": CERTIFIED_REASONING_EFFORTS,
        "request_count": request_count,
        "succeeded": succeeded,
        "upstream_id": catalog.upstream_id,
    }, sort_keys=True))
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
