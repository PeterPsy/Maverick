"""Service helpers for building the platform-managed MCP surface."""

from __future__ import annotations

from pathlib import Path

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.mcp.models import McpToolDefinition
from core.mcp.server import McpHostSurface, build_mcp_host_surface
from core.mcp.tool_registry import McpToolRegistry


def _core_tool_definitions() -> list[McpToolDefinition]:
    return [
        McpToolDefinition(
            tool_name="core.workspaces.list",
            description="Inspect the core workspace registry.",
            input_schema={},
            output_schema={"type": "object"},
            owner_kind="core",
            owner_id="workspaces",
            workspace_id=None,
            exposure_scope="core_global",
            workspace_safe=False,
            entrypoint_path=None,
        ),
        McpToolDefinition(
            tool_name="core.runtime.status",
            description="Inspect runtime session status for the active workspace.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            owner_kind="core",
            owner_id="runtime",
            workspace_id=None,
            exposure_scope="core_global",
            workspace_safe=True,
            entrypoint_path=None,
        ),
        McpToolDefinition(
            tool_name="core.providers.list",
            description="Inspect configured provider definitions and availability.",
            input_schema={},
            output_schema={"type": "object"},
            owner_kind="core",
            owner_id="providers",
            workspace_id=None,
            exposure_scope="core_global",
            workspace_safe=False,
            entrypoint_path=None,
        ),
    ]


def _workspace_app_tool_definitions(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
) -> list[McpToolDefinition]:
    definitions: list[McpToolDefinition] = []
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        if not parsed.contract.capabilities.mcp_tools:
            continue
        if parsed.contract.entrypoints.mcp is None:
            raise ValueError(
                f"App `{parsed.app_id}` declares MCP tools but no MCP entrypoint in its contract."
            )
        entrypoint_path = str((source_root / parsed.contract.entrypoints.mcp).resolve())
        for tool_name in parsed.contract.capabilities.mcp_tools:
            definitions.append(
                McpToolDefinition(
                    tool_name=tool_name,
                    description=f"App MCP tool exposed by `{parsed.app_id}`.",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    owner_kind="app",
                    owner_id=parsed.app_id,
                    workspace_id=workspace_id,
                    exposure_scope="workspace_enabled_app",
                    workspace_safe=True,
                    entrypoint_path=entrypoint_path,
                )
            )
    return definitions


def build_core_mcp_registry(
    *,
    app_store: AppStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> McpToolRegistry:
    """Build the platform-managed MCP registry for core and enabled app tools."""
    registry = McpToolRegistry()
    for definition in _core_tool_definitions():
        registry.register_tool(definition)
    if app_store is not None and workspace_id is not None:
        for definition in _workspace_app_tool_definitions(app_store, workspace_id=workspace_id, start_path=start_path):
            registry.register_tool(definition)
    return registry


def build_workspace_mcp_surface(
    *,
    app_store: AppStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
    transport: str = "stdio",
) -> McpHostSurface:
    """Build one MCP host surface for the requested workspace context."""
    registry = build_core_mcp_registry(app_store=app_store, workspace_id=workspace_id, start_path=start_path)
    return build_mcp_host_surface(registry, transport=transport)


def list_mcp_tools(
    *,
    app_store: AppStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> list[McpToolDefinition]:
    """List visible MCP tools for the requested workspace context."""
    return build_core_mcp_registry(app_store=app_store, workspace_id=workspace_id, start_path=start_path).list_tools()
