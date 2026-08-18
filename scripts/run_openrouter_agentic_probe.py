#!/usr/bin/env python3
"""Operator-only synthetic OpenRouter live probe used by certification."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.providers.agentic_protocol import (
    AgenticModelRequest, AgenticRequestContentBlock, AgenticToolDefinition,
    AgenticToolResult, EphemeralCredential,
)
from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from core.providers.openrouter_agentic_models import OPENROUTER_AGENTIC_MODEL_ID
from core.providers.openrouter_agentic_profile import openrouter_agentic_routing_constraint


async def _main() -> int:
    value = os.environ.get("MAVERICK_OPENROUTER_CERTIFICATION_API_KEY", "").strip()
    if not value:
        return 2
    request = _request()
    client = OpenRouterAgenticClient()
    first = [event async for event in client.create_response(
        request, credential=EphemeralCredential(value)
    )]
    call = next((event.tool_call for event in first if event.event_type == "tool_call"), None)
    private = next((
        event.provider_private_state for event in first
        if event.event_type == "provider_state"
    ), None)
    if call is None or private is None or any(event.event_type == "error" for event in first):
        return 1
    second = [event async for event in client.create_response(
        _request(private_state=private, tool_results=(AgenticToolResult(
            provider_tool_call_id=call.provider_tool_call_id,
            provider_tool_name=call.provider_tool_name,
            content_type="application/json", content=b'{"ok":true}', is_error=False,
        ),)), credential=EphemeralCredential(value)
    )]
    events = [*first, *second]
    succeeded = (
        any(event.event_type == "text_final" for event in second)
        and any(event.event_type == "completed" for event in second)
        and sum(event.event_type == "usage" for event in events) >= 2
        and sum(event.event_type == "provider_state" for event in events) >= 2
        and not any(event.event_type == "error" for event in events)
    )
    return 0 if succeeded else 1


def _request(*, private_state=None, tool_results=()) -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1", request_id="openrouter-live-synthetic-probe",
        correlation_id="openrouter-live-synthetic-probe",
        model_id=OPENROUTER_AGENTIC_MODEL_ID, reasoning_effort=None,
        content_blocks=(AgenticRequestContentBlock(
            content_block_id="synthetic-user", role="user", data_class="public",
            provenance="user_input", trust_level="trusted_platform",
            content_type="text/plain",
            content=b"Call maverick_probe_echo exactly once with any JSON object. Synthetic data only.",
        ),),
        tool_definitions=(AgenticToolDefinition(
            name="maverick_probe_echo", description="Synthetic certification echo.",
            input_schema={"type": "object", "additionalProperties": True},
        ),), tool_results=tool_results, provider_private_state=private_state,
        routing_constraint=openrouter_agentic_routing_constraint(), max_output_tokens=128,
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
