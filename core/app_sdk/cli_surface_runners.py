"""Core and app surface runners for the Maverick SDK CLI."""

from __future__ import annotations

from typing import Any

from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command
from core.mcp.service import call_mcp_tool
from core.app_sdk.cli_contexts import _cli_commands, _cli_context, _mcp_context, _mcp_tools
from core.app_sdk.cli_descriptors import (
    _app_scoped_id,
    _command_detail,
    _command_summary,
    _require_cli_command,
    _require_mcp_tool,
    _run_target_and_arguments,
    _single_id,
    _tool_detail,
    _tool_summary,
)
from core.app_sdk.cli_syntax import _die

def _run_core_cli(
    operation: str,
    tokens: list[str],
    *,
    options: dict[str, str],
    workspace_id: str,
    state,
    trusted_context: CliInvocationContext | None = None,
) -> dict[str, Any]:
    commands = [
        command
        for command in _cli_commands(state, workspace_id, options=options, trusted_context=trusted_context)
        if command.owner_kind == "core" or command.exposure_scope == "core_global"
    ]
    if operation == "list":
        if tokens:
            _die("usage: maverick core cli list --json")
        return {"workspace_id": workspace_id, "commands": [_command_summary(command) for command in commands]}
    if operation == "inspect":
        command_id = _single_id(tokens, "maverick core cli inspect <command_id> --json")
        _reject_app_cli_command_in_core_scope(command_id)
        command = _require_cli_command(commands, command_id)
        return {"workspace_id": workspace_id, "command": _command_detail(command)}
    if operation == "run":
        command_id, arguments = _run_target_and_arguments(tokens, options)
        _reject_app_cli_command_in_core_scope(command_id)
        command = _require_cli_command(commands, command_id)
        return run_core_cli_command(
            command_id=command.command_id,
            context=_cli_context(options, workspace_id, trusted_context=trusted_context),
            app_store=state.app_store,
            identity_store=state.identity_store,
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
            inter_agent_store=getattr(state, "inter_agent_store", None),
            provider_store=state.provider_store,
            secret_store=state.secret_store,
            recovery_store=state.recovery_store,
            observability_store=state.observability_store,
            app_event_bus=state.app_event_bus,
            workspace_id=workspace_id,
            start_path=state.repository_root,
            arguments=arguments,
        )
    _die("core CLI operation must be list, inspect, or run")


def _reject_app_cli_command_in_core_scope(command_id: str) -> None:
    parts = str(command_id or "").split(".")
    if len(parts) < 3 or parts[0] != "app":
        return
    app_id = parts[1]
    command_name = ".".join(parts[2:])
    _die(
        "This is an app CLI command. Use: "
        f"`maverick app {app_id} cli run {command_name} --json`"
    )


def _run_app_cli(
    app_id: str,
    operation: str,
    tokens: list[str],
    *,
    options: dict[str, str],
    workspace_id: str,
    state,
    trusted_context: CliInvocationContext | None = None,
) -> dict[str, Any]:
    prefix = f"app.{app_id}."
    commands = [
        command
        for command in _cli_commands(state, workspace_id, options=options, trusted_context=trusted_context)
        if command.owner_kind == "app" and command.owner_id == app_id
        and command.exposure_scope == "workspace_enabled_app"
    ]
    if operation == "list":
        if tokens:
            _die(f"usage: maverick app {app_id} cli list --json")
        return {"workspace_id": workspace_id, "app_id": app_id, "commands": [_command_summary(command, app_prefix=prefix) for command in commands]}
    if operation == "inspect":
        command = _require_cli_command(commands, _app_scoped_id(prefix, _single_id(tokens, f"maverick app {app_id} cli inspect <command_name> --json")))
        return {"workspace_id": workspace_id, "app_id": app_id, "command": _command_detail(command, app_prefix=prefix)}
    if operation == "run":
        command_name, arguments = _run_target_and_arguments(tokens, options)
        command = _require_cli_command(commands, _app_scoped_id(prefix, command_name))
        return run_core_cli_command(
            command_id=command.command_id,
            context=_cli_context(options, workspace_id, trusted_context=trusted_context),
            app_store=state.app_store,
            identity_store=state.identity_store,
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
            inter_agent_store=getattr(state, "inter_agent_store", None),
            provider_store=state.provider_store,
            secret_store=state.secret_store,
            recovery_store=state.recovery_store,
            observability_store=state.observability_store,
            app_event_bus=state.app_event_bus,
            workspace_id=workspace_id,
            start_path=state.repository_root,
            arguments=arguments,
        )
    _die("app CLI operation must be list, inspect, or run")

def _run_core_mcp(
    operation: str,
    tokens: list[str],
    *,
    options: dict[str, str],
    workspace_id: str,
    state,
    trusted_context: CliInvocationContext | None = None,
) -> dict[str, Any]:
    tools = [tool for tool in _mcp_tools(state, workspace_id, options=options, trusted_context=trusted_context) if tool.owner_kind == "core"]
    if operation == "list":
        if tokens:
            _die("usage: maverick core mcp list --json")
        return {"workspace_id": workspace_id, "tools": [_tool_summary(tool) for tool in tools]}
    if operation == "inspect":
        tool = _require_mcp_tool(tools, _single_id(tokens, "maverick core mcp inspect <tool_name> --json"))
        return {"workspace_id": workspace_id, "tool": _tool_detail(tool)}
    if operation == "call":
        tool_name, arguments = _run_target_and_arguments(tokens, options)
        tool = _require_mcp_tool(tools, tool_name)
        return call_mcp_tool(
            tool_name=tool.tool_name,
            context=_mcp_context(options, workspace_id, trusted_context=trusted_context),
            app_store=state.app_store,
            identity_store=state.identity_store,
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
            inter_agent_store=getattr(state, "inter_agent_store", None),
            provider_store=state.provider_store,
            secret_store=state.secret_store,
            recovery_store=state.recovery_store,
            observability_store=state.observability_store,
            app_event_bus=state.app_event_bus,
            workspace_id=workspace_id,
            start_path=state.repository_root,
            arguments=arguments,
        )
    _die("core MCP operation must be list, inspect, or call")

def _run_app_mcp(
    app_id: str,
    operation: str,
    tokens: list[str],
    *,
    options: dict[str, str],
    workspace_id: str,
    state,
    trusted_context: CliInvocationContext | None = None,
) -> dict[str, Any]:
    prefix = f"app.{app_id}."
    tools = [
        tool
        for tool in _mcp_tools(state, workspace_id, options=options, trusted_context=trusted_context)
        if tool.owner_kind == "app" and tool.owner_id == app_id
    ]
    if operation == "list":
        if tokens:
            _die(f"usage: maverick app {app_id} mcp list --json")
        return {"workspace_id": workspace_id, "app_id": app_id, "tools": [_tool_summary(tool, app_prefix=prefix) for tool in tools]}
    if operation == "inspect":
        tool = _require_mcp_tool(tools, _app_scoped_id(prefix, _single_id(tokens, f"maverick app {app_id} mcp inspect <tool_name> --json")))
        return {"workspace_id": workspace_id, "app_id": app_id, "tool": _tool_detail(tool, app_prefix=prefix)}
    if operation == "call":
        tool_name, arguments = _run_target_and_arguments(tokens, options)
        tool = _require_mcp_tool(tools, _app_scoped_id(prefix, tool_name))
        return call_mcp_tool(
            tool_name=tool.tool_name,
            context=_mcp_context(options, workspace_id, trusted_context=trusted_context),
            app_store=state.app_store,
            identity_store=state.identity_store,
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
            inter_agent_store=getattr(state, "inter_agent_store", None),
            provider_store=state.provider_store,
            secret_store=state.secret_store,
            recovery_store=state.recovery_store,
            observability_store=state.observability_store,
            app_event_bus=state.app_event_bus,
            workspace_id=workspace_id,
            start_path=state.repository_root,
            arguments=arguments,
        )
    _die("app MCP operation must be list, inspect, or call")
