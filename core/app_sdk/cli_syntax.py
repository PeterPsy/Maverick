"""Syntax, help, and argument parsing helpers for the Maverick SDK CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.cli.models import CliInvocationContext

def _split_wrapper_options(tokens: list[str]) -> tuple[dict[str, str], list[str]]:
    options: dict[str, str] = {}
    remaining: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"--json", "--operator"}:
            options[token[2:].replace("-", "_")] = "true"
            index += 1
            continue
        if token in {"--workspace", "--arguments-json"}:
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
                "       maverick core cli run <command_id> [--operator] [--arguments-json JSON] [--flag VALUE ...]",
                "       maverick core mcp list --json",
                "       maverick core mcp inspect <tool_name> --json",
                "       maverick core mcp call <tool_name> [--arguments-json JSON] [--flag VALUE ...]",
            ]
        )
    if topic == ["sdk"]:
        return "\n".join(
            [
                "usage: maverick sdk {templates|docs} --json",
                "       maverick sdk templates --json",
                "       maverick sdk docs --json",
            ]
        )
    if topic == ["core", "cli"]:
        return "\n".join(
            [
                "usage: maverick core cli {list|inspect|run} ...",
                "       maverick core cli list --json",
                "       maverick core cli inspect <command_id> --json",
                "       maverick core cli run <command_id> [--operator] [--arguments-json JSON] [--flag VALUE ...]",
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
            "usage: maverick [--repository-root PATH] {apps|core|app|sdk} ...",
            "       maverick apps list --json",
            "       maverick sdk templates --json",
            "       maverick sdk docs --json",
            "       maverick core cli list --json",
            "       maverick core mcp list --json",
            "       maverick app <app_id> cli list --json",
            "       maverick app <app_id> mcp list --json",
            "",
            "`--help` is human syntax help. Use `list` and `inspect` for machine-readable discovery.",
        ]
    )

def _workspace_id(
    options: dict[str, Any],
    repository_root: Path,
    *,
    trusted_context: CliInvocationContext | None = None,
) -> str:
    if trusted_context is not None and trusted_context.workspace_id:
        return trusted_context.workspace_id
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

def _die(message: str) -> None:
    raise SystemExit(message)
