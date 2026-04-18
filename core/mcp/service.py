"""Service helpers for building the platform-managed MCP surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.mcp.models import McpInvocationContext, McpInvocationPolicy, McpToolDefinition
from core.mcp.runner import McpRunner
from core.mcp.server import McpHostSurface, build_mcp_host_surface
from core.mcp.tool_registry import McpToolRegistry
from core.providers.store import ProviderStore
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.store import WorkspaceStore


def _core_tool_specs(
    *,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    def _workspace_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if workspace_store is None:
            return {"items": []}
        return {
            "items": [
                {
                    "workspace_id": item.workspace_id,
                    "name": item.name,
                    "status": item.status,
                }
                for item in workspace_store.list_workspaces()
            ]
        }

    def _runtime_status_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        return {"status": "runtime-surface-available", "workspace_id": arguments.get("workspace_id")}

    def _providers_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"items": []}
        return {
            "items": [
                {
                    "provider_id": item.provider_id,
                    "label": item.label,
                    "kind": item.kind,
                    "status": item.status,
                }
                for item in provider_store.list_provider_definitions()
            ]
        }

    return [
        (
            McpToolDefinition(
            tool_name="core.workspaces.list",
            description="Inspect the core workspace registry.",
            input_schema={},
            output_schema={"type": "object"},
            owner_kind="core",
            owner_id="workspaces",
            workspace_id=None,
            exposure_scope="core_global",
            invocation_policy=McpInvocationPolicy(
                operator_only=True,
                sandbox_agent_allowed=False,
                requires_workspace_context=False,
                requires_full_access=False,
            ),
            entrypoint_path=None,
        ),
            _workspace_list_handler,
        ),
        (
            McpToolDefinition(
            tool_name="core.runtime.status",
            description="Inspect runtime session status for the active workspace.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            owner_kind="core",
            owner_id="runtime",
            workspace_id=None,
            exposure_scope="core_global",
            invocation_policy=McpInvocationPolicy(
                operator_only=False,
                sandbox_agent_allowed=True,
                requires_workspace_context=True,
                requires_full_access=False,
            ),
            entrypoint_path=None,
        ),
            _runtime_status_handler,
        ),
        (
            McpToolDefinition(
            tool_name="core.providers.list",
            description="Inspect configured provider definitions and availability.",
            input_schema={},
            output_schema={"type": "object"},
            owner_kind="core",
            owner_id="providers",
            workspace_id=None,
            exposure_scope="core_global",
            invocation_policy=McpInvocationPolicy(
                operator_only=True,
                sandbox_agent_allowed=False,
                requires_workspace_context=False,
                requires_full_access=False,
            ),
            entrypoint_path=None,
        ),
            _providers_list_handler,
        ),
    ]


def _workspace_app_tool_definitions(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    definitions: list[tuple[McpToolDefinition, Any]] = []
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
            hosted_tool_name = f"app.{parsed.app_id}.{tool_name}"
            def _handler(
                arguments: dict[str, Any],
                context: McpInvocationContext,
                *,
                _entrypoint_path: str = entrypoint_path,
                _tool_name: str = tool_name,
                _workspace_id: str = workspace_id,
                _source_root: Path = source_root,
                _app_id: str = parsed.app_id,
            ) -> dict[str, Any]:
                return run_json_entrypoint(
                    _entrypoint_path,
                    payload={
                        "surface": "mcp",
                        "tool_name": _tool_name,
                        "workspace_id": _workspace_id,
                        "app_id": _app_id,
                        "arguments": arguments,
                    },
                    cwd=_source_root,
                )

            definitions.append(
                (
                    McpToolDefinition(
                        tool_name=hosted_tool_name,
                        description=f"App MCP tool exposed by `{parsed.app_id}`.",
                        input_schema={"type": "object"},
                        output_schema={"type": "object"},
                        owner_kind="app",
                        owner_id=parsed.app_id,
                        workspace_id=workspace_id,
                        exposure_scope="workspace_enabled_app",
                        invocation_policy=McpInvocationPolicy(
                            operator_only=False,
                            sandbox_agent_allowed=True,
                            requires_workspace_context=True,
                            requires_full_access=False,
                        ),
                        entrypoint_path=entrypoint_path,
                    ),
                    lambda arguments, context, _handler=_handler: _handler(arguments, context),
                )
            )
    return definitions


def build_core_mcp_registry(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> McpToolRegistry:
    """Build the platform-managed MCP registry for core and enabled app tools."""
    registry = McpToolRegistry()
    for definition, handler in _core_tool_specs(workspace_store=workspace_store, provider_store=provider_store):
        registry.register_tool(definition, handler)
    if app_store is not None and workspace_id is not None:
        for definition, handler in _workspace_app_tool_definitions(app_store, workspace_id=workspace_id, start_path=start_path):
            registry.register_tool(definition, handler)
    return registry


def build_workspace_mcp_surface(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
    transport: str = "stdio",
) -> McpHostSurface:
    """Build one MCP host surface for the requested workspace context."""
    registry = build_core_mcp_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        workspace_id=workspace_id,
        start_path=start_path,
    )
    return build_mcp_host_surface(registry, transport=transport)


def list_mcp_tools(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> list[McpToolDefinition]:
    """List visible MCP tools for the requested workspace context."""
    return build_core_mcp_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        workspace_id=workspace_id,
        start_path=start_path,
    ).list_tools()


def call_mcp_tool(
    *,
    tool_name: str,
    context: McpInvocationContext,
    arguments: dict[str, Any] | None = None,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> dict[str, Any]:
    """Invoke one visible MCP tool under a trusted invocation context."""
    registry = build_core_mcp_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        workspace_id=workspace_id,
        start_path=start_path,
    )
    return McpRunner(registry).call_tool(tool_name=tool_name, arguments=arguments or {}, context=context)
