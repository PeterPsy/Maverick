"""CLI and MCP descriptor helpers for the Maverick SDK CLI."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core.cli.models import CliCommandDefinition
from core.mcp.models import McpToolDefinition
from core.app_sdk.cli_syntax import _die, _surface_arguments

def _command_summary(command: CliCommandDefinition, *, app_prefix: str = "") -> dict[str, Any]:
    name = command.command_id.removeprefix(app_prefix) if app_prefix else command.command_id
    return {
        "name": name,
        "command_id": command.command_id,
        "owner_kind": command.owner_kind,
        "owner_id": command.owner_id,
        "description": command.description,
    }

def _command_detail(command: CliCommandDefinition, *, app_prefix: str = "") -> dict[str, Any]:
    return {
        **_command_summary(command, app_prefix=app_prefix),
        "workspace_id": command.workspace_id,
        "exposure_scope": command.exposure_scope,
        "argument_schema": command.argument_schema,
        "invocation_policy": asdict(command.invocation_policy),
    }

def _tool_summary(tool: McpToolDefinition, *, app_prefix: str = "") -> dict[str, Any]:
    name = tool.tool_name.removeprefix(app_prefix) if app_prefix else tool.tool_name
    return {
        "name": name,
        "tool_name": tool.tool_name,
        "owner_kind": tool.owner_kind,
        "owner_id": tool.owner_id,
        "description": tool.description,
    }

def _tool_detail(tool: McpToolDefinition, *, app_prefix: str = "") -> dict[str, Any]:
    return {
        **_tool_summary(tool, app_prefix=app_prefix),
        "workspace_id": tool.workspace_id,
        "exposure_scope": tool.exposure_scope,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "invocation_policy": asdict(tool.invocation_policy),
    }

def _require_cli_command(commands: list[CliCommandDefinition], command_id: str) -> CliCommandDefinition:
    for command in commands:
        if command.command_id == command_id:
            return command
    _die(f"CLI command is not available in this scope: {command_id}")

def _require_mcp_tool(tools: list[McpToolDefinition], tool_name: str) -> McpToolDefinition:
    for tool in tools:
        if tool.tool_name == tool_name:
            return tool
    _die(f"MCP tool is not available in this scope: {tool_name}")

def _single_id(tokens: list[str], usage: str) -> str:
    if len(tokens) != 1:
        _die(f"usage: {usage}")
    return tokens[0]

def _app_scoped_id(prefix: str, value: str) -> str:
    return value if value.startswith(prefix) else f"{prefix}{value}"

def _run_target_and_arguments(tokens: list[str], options: dict[str, str]) -> tuple[str, dict[str, Any]]:
    if not tokens:
        _die("run/call requires a target command or tool name")
    target = tokens[0]
    return target, _surface_arguments(tokens[1:], options.get("arguments_json"))
