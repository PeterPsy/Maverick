"""Execution runner for platform-managed MCP tools."""

from __future__ import annotations

from core.mcp.errors import McpInvocationNotAllowedError
from core.mcp.models import McpInvocationContext, McpInvocationPolicy
from core.mcp.tool_registry import McpToolRegistry


def enforce_mcp_invocation_policy(policy: McpInvocationPolicy, context: McpInvocationContext) -> None:
    """Enforce platform policy before one MCP tool may run."""
    if policy.operator_only and context.caller_kind != "operator":
        raise McpInvocationNotAllowedError("This MCP tool is operator-only.")
    if context.caller_kind == "sandbox_agent" and not policy.sandbox_agent_allowed:
        raise McpInvocationNotAllowedError("Sandboxed agents may not invoke this MCP tool.")
    if policy.requires_workspace_context and not context.workspace_id:
        raise McpInvocationNotAllowedError("This MCP tool requires a trusted workspace context.")
    if policy.requires_full_access and context.effective_mode != "full-access":
        raise McpInvocationNotAllowedError("This MCP tool requires full-access execution mode.")


class McpRunner:
    """Run registered MCP tools after policy enforcement."""

    def __init__(self, registry: McpToolRegistry) -> None:
        self.registry = registry

    def call_tool(
        self,
        *,
        tool_name: str,
        context: McpInvocationContext,
        arguments: dict | None = None,
    ) -> dict:
        """Invoke one visible MCP tool under a trusted invocation context."""
        definition = self.registry.get_tool(tool_name)
        enforce_mcp_invocation_policy(definition.invocation_policy, context)
        return self.registry.call_tool(tool_name, arguments or {}, context=context)
