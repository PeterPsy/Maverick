"""Workspace-oriented core MCP tools."""

from __future__ import annotations

from typing import Any

from core.mcp.core_tool_helpers import OPERATOR_ONLY, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.workspaces.store import WorkspaceStore


def workspace_tool_specs(*, workspace_store: WorkspaceStore | None = None) -> list[tuple[McpToolDefinition, Any]]:
    """Build workspace registry MCP tool specs."""
    def _workspace_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if workspace_store is None:
            return {"items": []}
        return {
            "items": [
                {"workspace_id": item.workspace_id, "name": item.name, "status": item.status}
                for item in workspace_store.list_workspaces()
            ]
        }

    return [
        (
            core_mcp_tool(
                tool_name="core.workspaces.list",
                description="Inspect the core workspace registry.",
                owner_id="workspaces",
                invocation_policy=OPERATOR_ONLY,
                input_schema={},
            ),
            _workspace_list_handler,
        )
    ]
