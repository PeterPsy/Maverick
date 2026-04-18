"""Models for core-owned and app-contributed MCP surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


McpOwnerKind = Literal["core", "app"]
McpExposureScope = Literal["core_global", "workspace_enabled_app"]


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
    workspace_safe: bool
    entrypoint_path: str | None


@dataclass(frozen=True)
class McpDiscoveryManifest:
    """Deterministic discovery manifest for one MCP host surface."""

    server_name: str
    tool_count: int
    tools: list[McpToolDefinition]
