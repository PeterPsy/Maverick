"""Core MCP tools for canonical developer context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.developer_context.service import list_documents, read_document
from core.mcp.core_tool_helpers import WORKSPACE_SAFE, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition


def developer_context_tool_specs(*, start_path: Path | None = None) -> list[tuple[McpToolDefinition, Any]]:
    """Build read-only MCP tools for canonical developer context."""

    def _list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        return {"items": list_documents()}

    def _read_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        return read_document(doc_id=str(arguments.get("doc_id") or ""), start_path=start_path)

    tool_specs = [
        ("developer-context.list", "List canonical developer context documents available through the core.", _list_handler, {}),
        ("developer-context.read", "Read one canonical developer context document by doc_id.", _read_handler, {"type": "object"}),
    ]
    return [
        (
            core_mcp_tool(
                tool_name=tool_name,
                description=description,
                owner_id="developer-context",
                invocation_policy=WORKSPACE_SAFE,
                input_schema=input_schema,
                agentic_result_data_class=(
                    "public"
                    if tool_name == "developer-context.list"
                    else None
                ),
            ),
            handler,
        )
        for tool_name, description, handler, input_schema in tool_specs
    ]
