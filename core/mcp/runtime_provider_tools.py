"""Runtime and provider core MCP tools."""

from __future__ import annotations

from typing import Any

from core.mcp.core_tool_helpers import OPERATOR_ONLY, WORKSPACE_SAFE, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.providers.store import ProviderStore
from core.runtime.store import RuntimeStore


def runtime_provider_tool_specs(
    *,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    """Build runtime and provider MCP tool specs."""
    def _runtime_status_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if runtime_store is None:
            return {"workspace_id": context.workspace_id, "sessions": []}
        workspace_id = arguments.get("workspace_id") or context.workspace_id
        if workspace_id is None:
            return {"workspace_id": None, "sessions": []}
        return {
            "workspace_id": workspace_id,
            "sessions": [
                {
                    "session_id": item.session_id,
                    "agent_id": item.agent_id,
                    "status": item.status,
                    "effective_mode": item.effective_mode,
                }
                for item in runtime_store.list_sessions(workspace_id)
            ],
        }

    def _providers_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"items": []}
        return {
            "items": [
                {"provider_id": item.provider_id, "label": item.label, "kind": item.kind, "status": item.status}
                for item in provider_store.list_provider_definitions()
            ]
        }

    return [
        (
            core_mcp_tool(
                tool_name="core.runtime.status",
                description="Inspect runtime session status for the active workspace.",
                owner_id="runtime",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _runtime_status_handler,
        ),
        (
            core_mcp_tool(
                tool_name="core.providers.list",
                description="Inspect configured provider definitions and availability.",
                owner_id="providers",
                invocation_policy=OPERATOR_ONLY,
                input_schema={},
            ),
            _providers_list_handler,
        ),
    ]
