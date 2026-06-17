"""MCP registry builder and invocation facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.store import AppStore
from core.mcp.errors import McpInvocationNotAllowedError
from core.mcp.app_tools import _workspace_app_tool_definitions
from core.mcp.core_tools import _core_tool_specs
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.mcp.runner import McpRunner
from core.mcp.server import McpHostSurface, build_mcp_host_surface
from core.mcp.tool_registry import McpToolRegistry
from core.inter_agent.store import InterAgentStore
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.recovery.store import RecoveryStore
from core.runtime.store import RuntimeStore
from core.secrets.store import SecretStore
from core.workspaces.store import WorkspaceStore

def build_core_mcp_registry(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    app_event_bus=None,
    workspace_id: str | None = None,
    context: McpInvocationContext | None = None,
    start_path: Path | None = None,
) -> McpToolRegistry:
    """Build the platform-managed MCP registry for core and enabled app tools."""
    registry = McpToolRegistry()
    for definition, handler in _core_tool_specs(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        start_path=start_path,
    ):
        registry.register_tool(definition, handler)
    if app_store is not None and workspace_id is not None:
        for definition, handler in _workspace_app_tool_definitions(
            app_store,
            workspace_id=workspace_id,
            workspace_store=workspace_store,
            provider_store=provider_store,
            runtime_store=runtime_store,
            context=context,
            secret_store=secret_store,
            observability_store=observability_store,
            app_event_bus=app_event_bus,
            start_path=start_path,
        ):
            registry.register_tool(definition, handler)
    return registry

def build_workspace_mcp_surface(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    app_event_bus=None,
    workspace_id: str | None = None,
    context: McpInvocationContext | None = None,
    start_path: Path | None = None,
    transport: str = "stdio",
) -> McpHostSurface:
    """Build one MCP host surface for the requested workspace context."""
    registry = build_core_mcp_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        app_event_bus=app_event_bus,
        workspace_id=workspace_id,
        context=context,
        start_path=start_path,
    )
    return build_mcp_host_surface(registry, transport=transport)

def list_mcp_tools(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    app_event_bus=None,
    workspace_id: str | None = None,
    context: McpInvocationContext | None = None,
    start_path: Path | None = None,
) -> list[McpToolDefinition]:
    """List visible MCP tools for the requested workspace context."""
    return build_core_mcp_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        app_event_bus=app_event_bus,
        workspace_id=workspace_id,
        context=context,
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
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    app_event_bus=None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> dict[str, Any]:
    """Invoke one visible MCP tool under a trusted invocation context."""
    registry = build_core_mcp_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        app_event_bus=app_event_bus,
        workspace_id=workspace_id,
        context=context,
        start_path=start_path,
    )
    try:
        return McpRunner(registry).call_tool(tool_name=tool_name, arguments=arguments or {}, context=context)
    except KeyError:
        if _hidden_app_tool_exists(
            tool_name=tool_name,
            app_store=app_store,
            workspace_store=workspace_store,
            provider_store=provider_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            secret_store=secret_store,
            recovery_store=recovery_store,
            provider_registry=provider_registry,
            observability_store=observability_store,
            app_event_bus=app_event_bus,
            workspace_id=workspace_id,
            start_path=start_path,
        ):
            raise McpInvocationNotAllowedError("This app MCP tool is not visible to the caller.") from None
        raise


def _hidden_app_tool_exists(
    *,
    tool_name: str,
    app_store: AppStore | None,
    workspace_store: WorkspaceStore | None,
    provider_store: ProviderStore | None,
    runtime_store: RuntimeStore | None,
    inter_agent_store: InterAgentStore | None,
    secret_store: SecretStore | None,
    recovery_store: RecoveryStore | None,
    provider_registry: ProviderRegistry | None,
    observability_store,
    app_event_bus,
    workspace_id: str | None,
    start_path: Path | None,
) -> bool:
    if app_store is None or workspace_id is None:
        return False
    unfiltered = build_core_mcp_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        app_event_bus=app_event_bus,
        workspace_id=workspace_id,
        context=None,
        start_path=start_path,
    )
    try:
        definition = unfiltered.get_tool(tool_name)
    except KeyError:
        return False
    return definition.owner_kind == "app"
