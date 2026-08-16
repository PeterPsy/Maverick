"""Models for core-owned and app-contributed MCP surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from core.execution_policy.models import ExecutionMode


McpOwnerKind = Literal["core", "app"]
McpExposureScope = Literal["core_global", "workspace_enabled_app"]
McpCallerKind = Literal["operator", "sandbox_agent", "full_access_agent"]
McpEffectClass = Literal["read", "mutating", "destructive", "unclassified"]


@dataclass(frozen=True)
class McpInvocationPolicy:
    """Policy gates applied before one MCP tool may run."""

    operator_only: bool
    sandbox_agent_allowed: bool
    requires_workspace_context: bool
    requires_full_access: bool


@dataclass(frozen=True)
class McpInvocationContext:
    """Trusted invocation context resolved by the platform before MCP execution."""

    caller_kind: McpCallerKind
    workspace_id: str | None
    agent_id: str | None
    effective_mode: ExecutionMode | None
    platform_role: str | None = None
    user_id: str | None = None
    workspace_role: str | None = None
    runtime_session_id: str | None = None
    app_mcp_timeout_seconds: float | None = None
    entrypoint_surface: Literal["mcp", "reference"] = "mcp"
    idempotency_key: str | None = None


@dataclass(frozen=True)
class McpToolDefinition:
    """Describe one MCP tool exposed through the Maverick platform host."""

    tool_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    owner_kind: McpOwnerKind
    owner_id: str
    workspace_id: str | None
    exposure_scope: McpExposureScope
    invocation_policy: McpInvocationPolicy
    entrypoint_path: str | None
    effect_class: McpEffectClass = "unclassified"
    supports_idempotency: bool = False
    safe_to_retry: bool = False


@dataclass(frozen=True)
class McpDiscoveryManifest:
    """Deterministic discovery manifest for one MCP host surface."""

    server_name: str
    tool_count: int
    tools: list[McpToolDefinition]
