"""Canonical in-memory tool results awaiting request-time egress approval."""

from __future__ import annotations

import json

from core.providers.agentic_protocol import AgenticToolResult


def make_agentic_tool_result(
    *,
    provider_tool_call_id: str,
    provider_tool_name: str,
    result: dict[str, object],
    is_error: bool,
) -> AgenticToolResult:
    return AgenticToolResult(
        provider_tool_call_id=provider_tool_call_id,
        provider_tool_name=provider_tool_name,
        content_type="application/json",
        content=json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
        is_error=is_error,
    )
