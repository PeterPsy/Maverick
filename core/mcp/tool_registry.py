"""Registry for core-owned and app-contributed MCP tool definitions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.mcp.models import McpDiscoveryManifest, McpToolDefinition


McpToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class McpToolRegistry:
    """Collect MCP tool definitions independently from transport wiring."""

    def __init__(self) -> None:
        self._tools: dict[str, McpToolDefinition] = {}
        self._handlers: dict[str, McpToolHandler] = {}

    def register_tool(self, definition: McpToolDefinition, handler: McpToolHandler) -> McpToolDefinition:
        """Register one MCP tool definition."""
        self._tools[definition.tool_name] = definition
        self._handlers[definition.tool_name] = handler
        return definition

    def list_tools(self) -> list[McpToolDefinition]:
        """Return all registered tools in deterministic order."""
        return [self._tools[tool_name] for tool_name in sorted(self._tools)]

    def get_tool(self, tool_name: str) -> McpToolDefinition:
        """Return one registered tool by canonical name."""
        return self._tools[tool_name]

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke one registered MCP tool through its resolved handler."""
        return self._handlers[tool_name](arguments or {})

    def discovery_manifest(self, *, server_name: str = "maverick") -> McpDiscoveryManifest:
        """Build a deterministic discovery manifest for the current registry."""
        tools = self.list_tools()
        return McpDiscoveryManifest(server_name=server_name, tool_count=len(tools), tools=tools)
