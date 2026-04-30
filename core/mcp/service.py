"""Public MCP service facade."""

from core.mcp.registry_builder import build_core_mcp_registry, build_workspace_mcp_surface, call_mcp_tool, list_mcp_tools

__all__ = ["build_core_mcp_registry", "build_workspace_mcp_surface", "call_mcp_tool", "list_mcp_tools"]
