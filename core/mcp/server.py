"""Transport-agnostic MCP host surface descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.mcp.models import McpDiscoveryManifest, McpInvocationContext
from core.mcp.runner import McpRunner
from core.mcp.tool_registry import McpToolRegistry


McpTransportKind = Literal["stdio", "http"]


@dataclass(frozen=True)
class McpHostSurface:
    """Describe one concrete MCP host surface built from a tool registry."""

    server_name: str
    transport: McpTransportKind
    mount_path: str
    manifest: McpDiscoveryManifest
    registry: McpToolRegistry

    def call_tool(self, tool_name: str, arguments: dict | None = None, *, context: McpInvocationContext) -> dict:
        """Invoke one visible MCP tool through the platform-managed host surface."""
        return McpRunner(self.registry).call_tool(tool_name=tool_name, arguments=arguments or {}, context=context)


def build_mcp_host_surface(
    registry: McpToolRegistry,
    *,
    server_name: str = "maverick",
    transport: McpTransportKind = "stdio",
    mount_path: str = "/mcp",
) -> McpHostSurface:
    """Build one MCP host surface without coupling registry to transport bootstrap."""
    return McpHostSurface(
        server_name=server_name,
        transport=transport,
        mount_path=mount_path,
        manifest=registry.discovery_manifest(server_name=server_name),
        registry=registry,
    )
