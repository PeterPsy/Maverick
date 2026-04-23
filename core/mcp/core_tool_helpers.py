"""Shared helpers for core-owned MCP tool definitions."""

from __future__ import annotations

from typing import Any

from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.observability.service import record_platform_audit, record_platform_event


OPERATOR_ONLY = McpInvocationPolicy(True, False, False, False)
OPERATOR_FULL_ACCESS = McpInvocationPolicy(True, False, True, True)
WORKSPACE_SAFE = McpInvocationPolicy(False, True, True, False)


def core_mcp_tool(
    *,
    tool_name: str,
    description: str,
    owner_id: str,
    invocation_policy: McpInvocationPolicy,
    input_schema: dict[str, Any] | None = None,
) -> McpToolDefinition:
    """Build one core-owned MCP tool definition."""
    return McpToolDefinition(
        tool_name=tool_name,
        description=description,
        input_schema=input_schema or {"type": "object"},
        output_schema={"type": "object"},
        owner_kind="core",
        owner_id=owner_id,
        workspace_id=None,
        exposure_scope="core_global",
        invocation_policy=invocation_policy,
        entrypoint_path=None,
    )


def record_mcp_audit(
    observability_store,
    *,
    event_type: str,
    payload: dict[str, Any],
    workspace_id: str | None = None,
    provider_id: str | None = None,
    runtime_session_id: str | None = None,
) -> None:
    """Emit MCP audit and event records when a store is configured."""
    if observability_store is None:
        return
    record_platform_audit(
        observability_store,
        action=event_type,
        status="succeeded",
        source_domain="mcp",
        detail=event_type,
        workspace_id=workspace_id,
        provider_id=provider_id,
        runtime_session_id=runtime_session_id,
        payload=payload,
    )
    record_platform_event(
        observability_store,
        event_type=event_type,
        event_plane="platform" if runtime_session_id is None else "runtime",
        source_domain="mcp",
        workspace_id=workspace_id,
        provider_id=provider_id,
        runtime_session_id=runtime_session_id,
        payload=payload,
    )
