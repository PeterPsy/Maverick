"""Invocation context and registry helpers for the Maverick SDK CLI."""

from __future__ import annotations

from dataclasses import replace

from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.cli.service import list_core_cli_commands
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.mcp.service import list_mcp_tools

def _cli_commands(
    state,
    workspace_id: str,
    *,
    options: dict[str, str] | None = None,
    trusted_context: CliInvocationContext | None = None,
) -> list[CliCommandDefinition]:
    options = options or {}
    return list_core_cli_commands(
        app_store=state.app_store,
        identity_store=state.identity_store,
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        inter_agent_store=getattr(state, "inter_agent_store", None),
        provider_store=state.provider_store,
        secret_store=state.secret_store,
        recovery_store=state.recovery_store,
        job_service=getattr(state, "job_service", None),
        observability_store=state.observability_store,
        runtime_event_bus=getattr(state, "runtime_event_bus", None),
        runtime_thread_event_bus=getattr(state, "runtime_thread_event_bus", None),
        app_event_bus=state.app_event_bus,
        workspace_id=workspace_id,
        context=_cli_context(options, workspace_id, trusted_context=trusted_context),
        start_path=state.repository_root,
    )

def _mcp_tools(
    state,
    workspace_id: str,
    *,
    options: dict[str, str] | None = None,
    trusted_context: CliInvocationContext | None = None,
) -> list[McpToolDefinition]:
    options = options or {}
    return list_mcp_tools(
        app_store=state.app_store,
        identity_store=state.identity_store,
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        inter_agent_store=getattr(state, "inter_agent_store", None),
        provider_store=state.provider_store,
        secret_store=state.secret_store,
        recovery_store=state.recovery_store,
        job_service=getattr(state, "job_service", None),
        observability_store=state.observability_store,
        runtime_event_bus=getattr(state, "runtime_event_bus", None),
        runtime_thread_event_bus=getattr(state, "runtime_thread_event_bus", None),
        app_event_bus=state.app_event_bus,
        workspace_id=workspace_id,
        context=_mcp_context(options, workspace_id, trusted_context=trusted_context),
        start_path=state.repository_root,
    )

def _cli_context(
    options: dict[str, str],
    workspace_id: str,
    *,
    trusted_context: CliInvocationContext | None = None,
    default_caller_kind: str = "sandbox_agent",
    default_effective_mode: str = "sandbox",
) -> CliInvocationContext:
    if trusted_context is not None:
        return replace(trusted_context, workspace_id=workspace_id)
    if options.get("operator") == "true":
        default_caller_kind = "operator"
        default_effective_mode = "full-access"
    return CliInvocationContext(
        caller_kind=default_caller_kind,
        workspace_id=workspace_id,
        agent_id=None,
        effective_mode=default_effective_mode,
        platform_role=None,
        user_id=None,
        workspace_role=None,
    )

def _mcp_context(
    options: dict[str, str],
    workspace_id: str,
    *,
    trusted_context: CliInvocationContext | None = None,
) -> McpInvocationContext:
    if trusted_context is not None:
        trusted_cli_context = replace(trusted_context, workspace_id=workspace_id)
        return McpInvocationContext(
            caller_kind=trusted_cli_context.caller_kind,
            workspace_id=trusted_cli_context.workspace_id,
            agent_id=trusted_cli_context.agent_id,
            effective_mode=trusted_cli_context.effective_mode,
            platform_role=trusted_cli_context.platform_role,
            user_id=trusted_cli_context.user_id,
            workspace_role=trusted_cli_context.workspace_role,
            runtime_session_id=trusted_cli_context.runtime_session_id,
        )
    return McpInvocationContext(
        caller_kind="sandbox_agent",
        workspace_id=workspace_id,
        agent_id=None,
        effective_mode="sandbox",
        platform_role=None,
        user_id=None,
        workspace_role=None,
    )
