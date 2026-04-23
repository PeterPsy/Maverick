"""Command-line wrapper for Maverick platform CLI and MCP surfaces."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

from core.api.platform_state import bootstrap_platform_state
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.mcp.service import call_mcp_tool, list_mcp_tools


SDK_ACTIONS = {"create", "validate", "register-local", "install-local", "status", "package"}


def main(argv: list[str] | None = None) -> int:
    """Run the Maverick CLI wrapper."""
    raw_args = list(argv if argv is not None else sys.argv[1:])
    repository_root, args = _extract_repository_root(raw_args)
    if not args:
        _die("usage: maverick [--repository-root PATH] {apps|core|app} ...")
    if _wants_help(args):
        print(_help_text(args))
        return 0

    state = bootstrap_platform_state(start_path=repository_root)
    result = run_cli_json(args, state=state, repository_root=state.repository_root)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def run_cli_json(argv: list[str], *, state, repository_root: Path | None = None) -> dict[str, Any]:
    """Run one Maverick CLI command and return the JSON payload without printing."""
    repository_root_arg, args = _extract_repository_root(list(argv))
    if not args:
        _die("usage: maverick [--repository-root PATH] {apps|core|app} ...")
    if _wants_help(args):
        return {"help": _help_text(args)}
    if repository_root is None and repository_root_arg is not None:
        repository_root = repository_root_arg
    if repository_root is None:
        repository_root = state.repository_root
    domain = args[0]
    if domain == "apps":
        result = _run_apps(args[1:], state=state)
    elif domain == "core":
        result = _run_core(args[1:], state=state)
    elif domain == "app":
        result = _run_app(args[1:], state=state)
    else:
        _die(f"unknown Maverick command domain: {domain}")
    return result


def _run_apps(tokens: list[str], *, state) -> dict[str, Any]:
    options, remaining = _split_wrapper_options(tokens)
    if remaining != ["list"]:
        _die("usage: maverick apps list --json")
    workspace_id = _workspace_id(options, state.repository_root)
    apps = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=workspace_id):
        _source_root, parsed = resolve_workspace_app_surface(
            state.app_store,
            binding=binding,
            start_path=state.repository_root,
        )
        apps.append(
            {
                "app_id": parsed.app_id,
                "name": parsed.name,
                "description": parsed.description,
                "version": parsed.version,
                "capabilities": {
                    "cli": bool(parsed.contract.capabilities.cli_commands),
                    "mcp": bool(parsed.contract.capabilities.mcp_tools),
                    "skills": list(parsed.contract.capabilities.skills),
                },
            }
        )
    return {"workspace_id": workspace_id, "apps": apps}


def _run_core(tokens: list[str], *, state) -> dict[str, Any]:
    if len(tokens) < 2:
        _die("usage: maverick core {cli|mcp} {list|inspect|run|call} ...")
    surface, operation = tokens[0], tokens[1]
    options, remaining = _split_wrapper_options(tokens[2:])
    workspace_id = _workspace_id(options, state.repository_root)
    if surface == "cli":
        return _run_core_cli(operation, remaining, options=options, workspace_id=workspace_id, state=state)
    if surface == "mcp":
        return _run_core_mcp(operation, remaining, options=options, workspace_id=workspace_id, state=state)
    _die("core surface must be `cli` or `mcp`")


def _run_app(tokens: list[str], *, state) -> dict[str, Any]:
    if not tokens:
        _die("usage: maverick app <app_id> {cli|mcp|frontend} ...")
    if tokens[0] in SDK_ACTIONS:
        return _run_app_sdk(tokens, state=state)
    if len(tokens) >= 3 and tokens[1] == "frontend":
        app_id, _surface, operation = tokens[0], tokens[1], tokens[2]
        options, remaining = _split_wrapper_options(tokens[3:])
        workspace_id = _workspace_id(options, state.repository_root)
        return _run_app_frontend(app_id, operation, remaining, options=options, workspace_id=workspace_id, state=state)
    if len(tokens) < 3:
        _die("usage: maverick app <app_id> {cli|mcp|frontend} ...")
    app_id, surface, operation = tokens[0], tokens[1], tokens[2]
    options, remaining = _split_wrapper_options(tokens[3:])
    workspace_id = _workspace_id(options, state.repository_root)
    if surface == "cli":
        return _run_app_cli(app_id, operation, remaining, options=options, workspace_id=workspace_id, state=state)
    if surface == "mcp":
        return _run_app_mcp(app_id, operation, remaining, options=options, workspace_id=workspace_id, state=state)
    _die("app surface must be `cli`, `mcp`, or `frontend`")


def _run_app_frontend(app_id: str, operation: str, tokens: list[str], *, options: dict[str, str], workspace_id: str, state) -> dict[str, Any]:
    if operation != "build" or tokens:
        _die(f"usage: maverick app {app_id} frontend build --json")
    return run_core_cli_command(
        command_id=f"app.{app_id}.frontend.build",
        context=CliInvocationContext(
            caller_kind=options.get("caller_kind", "operator"),
            workspace_id=workspace_id,
            agent_id=options.get("agent_id"),
            effective_mode=options.get("effective_mode", "full-access"),
            platform_role=options.get("platform_role"),
        ),
        app_store=state.app_store,
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        provider_store=state.provider_store,
        secret_store=state.secret_store,
        recovery_store=state.recovery_store,
        observability_store=state.observability_store,
        app_event_bus=state.app_event_bus,
        workspace_id=workspace_id,
        start_path=state.repository_root,
        arguments={"workspace_id": workspace_id},
    )


def _run_core_cli(operation: str, tokens: list[str], *, options: dict[str, str], workspace_id: str, state) -> dict[str, Any]:
    commands = [command for command in _cli_commands(state, workspace_id) if command.owner_kind == "core"]
    if operation == "list":
        if tokens:
            _die("usage: maverick core cli list --json")
        return {"workspace_id": workspace_id, "commands": [_command_summary(command) for command in commands]}
    if operation == "inspect":
        command = _require_cli_command(commands, _single_id(tokens, "maverick core cli inspect <command_id> --json"))
        return {"workspace_id": workspace_id, "command": _command_detail(command)}
    if operation == "run":
        command_id, arguments = _run_target_and_arguments(tokens, options)
        command = _require_cli_command(commands, command_id)
        return run_core_cli_command(
            command_id=command.command_id,
            context=_cli_context(options, workspace_id),
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
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


def _run_app_cli(app_id: str, operation: str, tokens: list[str], *, options: dict[str, str], workspace_id: str, state) -> dict[str, Any]:
    prefix = f"app.{app_id}."
    commands = [
        command
        for command in _cli_commands(state, workspace_id)
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
            context=_cli_context(options, workspace_id),
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
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


def _run_core_mcp(operation: str, tokens: list[str], *, options: dict[str, str], workspace_id: str, state) -> dict[str, Any]:
    tools = [tool for tool in _mcp_tools(state, workspace_id) if tool.owner_kind == "core"]
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
            context=_mcp_context(options, workspace_id),
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
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


def _run_app_mcp(app_id: str, operation: str, tokens: list[str], *, options: dict[str, str], workspace_id: str, state) -> dict[str, Any]:
    prefix = f"app.{app_id}."
    tools = [
        tool
        for tool in _mcp_tools(state, workspace_id)
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
            context=_mcp_context(options, workspace_id),
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
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


def _run_app_sdk(tokens: list[str], *, state) -> dict[str, Any]:
    parser = _sdk_parser()
    args = parser.parse_args(tokens)
    workspace_id = _workspace_id(vars(args), state.repository_root)
    context = CliInvocationContext(
        caller_kind="operator",
        workspace_id=workspace_id,
        agent_id=None,
        effective_mode="full-access",
        platform_role="admin",
    )
    return run_core_cli_command(
        command_id=f"core.app-sdk.{args.action}",
        context=context,
        app_store=state.app_store,
        observability_store=state.observability_store,
        workspace_id=workspace_id,
        start_path=state.repository_root,
        arguments=_sdk_arguments(args, workspace_id=workspace_id),
    )


def _cli_commands(state, workspace_id: str) -> list[CliCommandDefinition]:
    return list_core_cli_commands(
        app_store=state.app_store,
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        provider_store=state.provider_store,
        secret_store=state.secret_store,
        recovery_store=state.recovery_store,
        observability_store=state.observability_store,
        app_event_bus=state.app_event_bus,
        workspace_id=workspace_id,
        start_path=state.repository_root,
    )


def _mcp_tools(state, workspace_id: str) -> list[McpToolDefinition]:
    return list_mcp_tools(
        app_store=state.app_store,
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        provider_store=state.provider_store,
        secret_store=state.secret_store,
        recovery_store=state.recovery_store,
        observability_store=state.observability_store,
        app_event_bus=state.app_event_bus,
        workspace_id=workspace_id,
        start_path=state.repository_root,
    )


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


def _cli_context(options: dict[str, str], workspace_id: str) -> CliInvocationContext:
    return CliInvocationContext(
        caller_kind=options.get("caller_kind", "sandbox_agent"),
        workspace_id=workspace_id,
        agent_id=options.get("agent_id"),
        effective_mode=options.get("effective_mode", "sandbox"),
        platform_role=options.get("platform_role"),
    )


def _mcp_context(options: dict[str, str], workspace_id: str) -> McpInvocationContext:
    return McpInvocationContext(
        caller_kind=options.get("caller_kind", "sandbox_agent"),
        workspace_id=workspace_id,
        agent_id=options.get("agent_id"),
        effective_mode=options.get("effective_mode", "sandbox"),
    )


def _split_wrapper_options(tokens: list[str]) -> tuple[dict[str, str], list[str]]:
    options: dict[str, str] = {}
    remaining: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"--json"}:
            options["json"] = "true"
            index += 1
            continue
        if token in {"--workspace", "--caller-kind", "--effective-mode", "--agent-id", "--arguments-json", "--platform-role"}:
            if index + 1 >= len(tokens):
                _die(f"{token} requires a value")
            options[token[2:].replace("-", "_")] = tokens[index + 1]
            index += 2
            continue
        remaining.append(token)
        index += 1
    return options, remaining


def _extract_repository_root(tokens: list[str]) -> tuple[Path | None, list[str]]:
    repository_root: Path | None = None
    remaining: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--repository-root":
            if index + 1 >= len(tokens):
                _die("--repository-root requires a value")
            repository_root = Path(tokens[index + 1]).resolve()
            index += 2
            continue
        remaining.append(token)
        index += 1
    return repository_root, remaining


def _wants_help(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if tokens[-1] not in {"--help", "-h", "help"}:
        return False
    if tokens[0] == "app" and len(tokens) > 1 and tokens[1] in SDK_ACTIONS:
        return False
    return True


def _help_text(tokens: list[str]) -> str:
    topic = tokens[:-1] if tokens[-1] in {"--help", "-h", "help"} else tokens
    if not topic:
        return _root_help()
    if topic == ["apps"]:
        return "usage: maverick apps list --json"
    if topic == ["core"]:
        return "\n".join(
            [
                "usage: maverick core {cli|mcp} ...",
                "       maverick core cli list --json",
                "       maverick core cli inspect <command_id> --json",
                "       maverick core cli run <command_id> [--arguments-json JSON] [--flag VALUE ...]",
                "       maverick core mcp list --json",
                "       maverick core mcp inspect <tool_name> --json",
                "       maverick core mcp call <tool_name> [--arguments-json JSON] [--flag VALUE ...]",
            ]
        )
    if topic == ["core", "cli"]:
        return "\n".join(
            [
                "usage: maverick core cli {list|inspect|run} ...",
                "       maverick core cli list --json",
                "       maverick core cli inspect <command_id> --json",
                "       maverick core cli run <command_id> [--arguments-json JSON] [--flag VALUE ...]",
            ]
        )
    if topic == ["core", "mcp"]:
        return "\n".join(
            [
                "usage: maverick core mcp {list|inspect|call} ...",
                "       maverick core mcp list --json",
                "       maverick core mcp inspect <tool_name> --json",
                "       maverick core mcp call <tool_name> [--arguments-json JSON] [--flag VALUE ...]",
            ]
        )
    if topic == ["app"]:
        return "\n".join(
            [
                "usage: maverick app <app_id> {cli|mcp|frontend} ...",
                "       maverick app <app_id> cli list --json",
                "       maverick app <app_id> cli inspect <command_name> --json",
                "       maverick app <app_id> cli run <command_name> [--arguments-json JSON] [--flag VALUE ...]",
                "       maverick app <app_id> mcp list --json",
                "       maverick app <app_id> mcp inspect <tool_name> --json",
                "       maverick app <app_id> mcp call <tool_name> [--arguments-json JSON] [--flag VALUE ...]",
                "       maverick app <app_id> frontend build --json",
            ]
        )
    if len(topic) == 2 and topic[0] == "app":
        app_id = topic[1]
        return "\n".join(
            [
                f"usage: maverick app {app_id} {{cli|mcp|frontend}} ...",
                f"       maverick app {app_id} cli list --json",
                f"       maverick app {app_id} cli inspect <command_name> --json",
                f"       maverick app {app_id} cli run <command_name> [--arguments-json JSON] [--flag VALUE ...]",
                f"       maverick app {app_id} mcp list --json",
                f"       maverick app {app_id} mcp inspect <tool_name> --json",
                f"       maverick app {app_id} mcp call <tool_name> [--arguments-json JSON] [--flag VALUE ...]",
                f"       maverick app {app_id} frontend build --json",
            ]
        )
    if len(topic) == 3 and topic[0] == "app" and topic[2] == "frontend":
        app_id = topic[1]
        return f"usage: maverick app {app_id} frontend build --json"
    if len(topic) == 3 and topic[0] == "app" and topic[2] == "cli":
        app_id = topic[1]
        return "\n".join(
            [
                f"usage: maverick app {app_id} cli {{list|inspect|run}} ...",
                f"       maverick app {app_id} cli list --json",
                f"       maverick app {app_id} cli inspect <command_name> --json",
                f"       maverick app {app_id} cli run <command_name> [--arguments-json JSON] [--flag VALUE ...]",
            ]
        )
    if len(topic) == 3 and topic[0] == "app" and topic[2] == "mcp":
        app_id = topic[1]
        return "\n".join(
            [
                f"usage: maverick app {app_id} mcp {{list|inspect|call}} ...",
                f"       maverick app {app_id} mcp list --json",
                f"       maverick app {app_id} mcp inspect <tool_name> --json",
                f"       maverick app {app_id} mcp call <tool_name> [--arguments-json JSON] [--flag VALUE ...]",
            ]
        )
    return _root_help()


def _root_help() -> str:
    return "\n".join(
        [
            "usage: maverick [--repository-root PATH] {apps|core|app} ...",
            "       maverick apps list --json",
            "       maverick core cli list --json",
            "       maverick core mcp list --json",
            "       maverick app <app_id> cli list --json",
            "       maverick app <app_id> mcp list --json",
            "",
            "`--help` is human syntax help. Use `list` and `inspect` for machine-readable discovery.",
        ]
    )


def _workspace_id(options: dict[str, Any], repository_root: Path) -> str:
    configured = str(options.get("workspace") or "").strip()
    if configured:
        return configured
    current = Path.cwd().resolve(strict=False)
    workspaces_root = (repository_root / "workspaces").resolve(strict=False)
    try:
        relative = current.relative_to(workspaces_root)
    except ValueError:
        return "default"
    return relative.parts[0] if relative.parts else "default"


def _surface_arguments(tokens: list[str], raw_json: str | None) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    if raw_json:
        loaded = json.loads(raw_json)
        if not isinstance(loaded, dict):
            _die("--arguments-json must decode to a JSON object")
        arguments.update(loaded)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            _die(f"unexpected positional argument for app surface: {token}")
        key = token[2:].replace("-", "_")
        if not key:
            _die("empty argument flag is not allowed")
        if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
            value: Any = True
            index += 1
        else:
            value = _parse_scalar(tokens[index + 1])
            index += 2
        if key in arguments:
            previous = arguments[key]
            if isinstance(previous, list):
                previous.append(value)
            else:
                arguments[key] = [previous, value]
        else:
            arguments[key] = value
    return arguments


def _parse_scalar(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _sdk_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maverick app")
    subparsers = parser.add_subparsers(dest="action", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("app_id")
    create.add_argument("--template", dest="template_id", default="minimal")
    create.add_argument("--workspace", default=None)
    create.add_argument("--target-kind", default="workspace_local")
    create.add_argument("--name", default=None)
    create.add_argument("--description", default=None)
    create.add_argument("--publisher", default="workspace")
    create.add_argument("--version", default="0.1.0")
    create.add_argument("--entity", dest="entities", action="append", default=None)
    create.add_argument("--overwrite", action="store_true")
    for action in ("validate", "register-local", "install-local", "status"):
        command = subparsers.add_parser(action)
        command.add_argument("app_id")
        command.add_argument("--workspace", default=None)
    package = subparsers.add_parser("package")
    package.add_argument("--workspace", default=None)
    package.add_argument("--app-root", required=True)
    package.add_argument("--output-path", default=None)
    return parser


def _sdk_arguments(args, *, workspace_id: str) -> dict[str, Any]:
    if args.action == "create":
        return {
            "app_id": args.app_id,
            "template_id": args.template_id,
            "workspace_id": workspace_id,
            "target_kind": args.target_kind,
            "name": args.name,
            "description": args.description,
            "publisher": args.publisher,
            "version": args.version,
            "entities": args.entities,
            "overwrite": args.overwrite,
        }
    if args.action == "package":
        return {"app_root": args.app_root, "output_path": args.output_path}
    return {"app_id": args.app_id, "workspace_id": workspace_id}


def _die(message: str) -> None:
    raise SystemExit(message)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
