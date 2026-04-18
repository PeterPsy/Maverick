"""Registry for core-owned and app-contributed MCP tool definitions."""

from __future__ import annotations

from core.mcp.models import McpDiscoveryManifest, McpToolDefinition


class McpToolRegistry:
    """Collect MCP tool definitions independently from transport wiring."""

    def __init__(self) -> None:
        self._tools: dict[str, McpToolDefinition] = {}

    def register_tool(self, definition: McpToolDefinition) -> McpToolDefinition:
        """Register one MCP tool definition."""
        self._tools[definition.tool_name] = definition
        return definition

    def list_tools(self) -> list[McpToolDefinition]:
        """Return all registered tools in deterministic order."""
        return [self._tools[tool_name] for tool_name in sorted(self._tools)]

    def get_tool(self, tool_name: str) -> McpToolDefinition:
        """Return one registered tool by canonical name."""
        return self._tools[tool_name]

    def discovery_manifest(self, *, server_name: str = "maverick") -> McpDiscoveryManifest:
        """Build a deterministic discovery manifest for the current registry."""
        tools = self.list_tools()
        return McpDiscoveryManifest(server_name=server_name, tool_count=len(tools), tools=tools)
