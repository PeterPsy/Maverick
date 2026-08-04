"""Core-owned MCP tool composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.store import AppStore
from core.identity.store import IdentityStore
from core.mcp.developer_context_tools import developer_context_tool_specs
from core.mcp.inter_agent_tools import inter_agent_tool_specs
from core.mcp.persistence_tools import persistence_tool_specs
from core.mcp.models import McpToolDefinition
from core.mcp.recovery_tools import recovery_tool_specs
from core.mcp.runtime_provider_tools import runtime_provider_tool_specs
from core.mcp.secret_tools import secret_tool_specs
from core.mcp.workspace_tools import workspace_tool_specs
from core.inter_agent.store import InterAgentStore
from core.inter_agent.orchestration_resume import OrchestrationResume
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.recovery.store import RecoveryStore
from core.runtime.store import RuntimeStore
from core.secrets.store import SecretStore
from core.workspaces.store import WorkspaceStore


def _core_tool_specs(
    *,
    app_store: AppStore | None = None,
    identity_store: IdentityStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    runtime_event_bus=None,
    runtime_thread_event_bus=None,
    app_event_bus=None,
    orchestration_resume: OrchestrationResume | None = None,
    start_path: Path | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    """Build all core-owned MCP tool specs without mixing tool domains."""
    specs: list[tuple[McpToolDefinition, Any]] = []
    specs.extend(workspace_tool_specs(workspace_store=workspace_store))
    specs.extend(persistence_tool_specs(start_path=start_path))
    specs.extend(developer_context_tool_specs(start_path=start_path))
    specs.extend(
        runtime_provider_tool_specs(
            provider_store=provider_store,
            runtime_store=runtime_store,
            provider_registry=provider_registry,
            secret_store=secret_store,
            observability_store=observability_store,
        )
    )
    specs.extend(
        inter_agent_tool_specs(
            app_store=app_store,
            identity_store=identity_store,
            workspace_store=workspace_store,
            provider_store=provider_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            secret_store=secret_store,
            observability_store=observability_store,
            runtime_event_bus=runtime_event_bus,
            runtime_thread_event_bus=runtime_thread_event_bus,
            app_event_bus=app_event_bus,
            orchestration_resume=orchestration_resume,
            start_path=start_path,
        )
    )
    specs.extend(
        secret_tool_specs(
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            start_path=start_path,
        )
    )
    specs.extend(
        recovery_tool_specs(
            app_store=app_store,
            runtime_store=runtime_store,
            recovery_store=recovery_store,
            workspace_store=workspace_store,
            provider_registry=provider_registry,
            observability_store=observability_store,
            start_path=start_path,
        )
    )
    return specs
