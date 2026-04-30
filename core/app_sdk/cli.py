"""Command-line wrapper for Maverick platform CLI and MCP surfaces."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from core.api.platform_state import bootstrap_platform_state
from core.app_sdk.docs import sdk_docs_markdown
from core.app_sdk.templates import SUPPORTED_TEMPLATES
from core.app_sdk.cli_surfaces import (
    _cli_context,
    _die,
    _extract_repository_root,
    _help_text,
    _run_app_cli,
    _run_app_mcp,
    _run_core_cli,
    _run_core_mcp,
    _split_wrapper_options,
    _workspace_id,
    _wants_help,
)
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.authorization.service import can_mount_app_visibility
from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command


SDK_DOMAIN_ACTIONS = {"templates", "docs"}


def main(argv: list[str] | None = None) -> int:
    """Run the Maverick CLI wrapper."""
    raw_args = list(argv if argv is not None else sys.argv[1:])
    repository_root, args = _extract_repository_root(raw_args)
    if not args:
        _die("usage: maverick [--repository-root PATH] {apps|core|app|sdk} ...")
    if _wants_help(args):
        print(_help_text(args))
        return 0

    state = bootstrap_platform_state(start_path=repository_root)
    result = run_cli_json(args, state=state, repository_root=state.repository_root)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def run_cli_json(
    argv: list[str],
    *,
    state,
    repository_root: Path | None = None,
    trusted_context: CliInvocationContext | None = None,
) -> dict[str, Any]:
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
        result = _run_apps(args[1:], state=state, trusted_context=trusted_context)
    elif domain == "core":
        result = _run_core(args[1:], state=state, trusted_context=trusted_context)
    elif domain == "app":
        result = _run_app(args[1:], state=state, trusted_context=trusted_context)
    elif domain == "sdk":
        result = _run_sdk_domain(args[1:], state=state, trusted_context=trusted_context)
    else:
        _die(f"unknown Maverick command domain: {domain}")
    return result


def _run_apps(tokens: list[str], *, state, trusted_context: CliInvocationContext | None = None) -> dict[str, Any]:
    options, remaining = _split_wrapper_options(tokens)
    if remaining != ["list"]:
        _die("usage: maverick apps list --json")
    workspace_id = _workspace_id(options, state.repository_root, trusted_context=trusted_context)
    context = _cli_context(options, workspace_id, trusted_context=trusted_context)
    apps = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=workspace_id):
        _source_root, parsed = resolve_workspace_app_surface(
            state.app_store,
            binding=binding,
            start_path=state.repository_root,
        )
        if not can_mount_app_visibility(
            state.workspace_store,
            user=None,
            workspace_id=workspace_id,
            platform_roles=parsed.contract.visibility.platform_roles,
            workspace_roles=parsed.contract.visibility.workspace_roles,
            capabilities=parsed.contract.visibility.capabilities,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
        ):
            continue
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


def _run_sdk_domain(tokens: list[str], *, state, trusted_context: CliInvocationContext | None = None) -> dict[str, Any]:
    options, remaining = _split_wrapper_options(tokens)
    if len(remaining) != 1 or remaining[0] not in SDK_DOMAIN_ACTIONS:
        _die("usage: maverick sdk {templates|docs} --json")
    workspace_id = _workspace_id(options, state.repository_root, trusted_context=trusted_context)
    action = remaining[0]
    if action == "templates":
        return {"workspace_id": workspace_id, "templates": sorted(SUPPORTED_TEMPLATES)}
    return {"workspace_id": workspace_id, "format": "markdown", "content": sdk_docs_markdown()}


def _run_core(tokens: list[str], *, state, trusted_context: CliInvocationContext | None = None) -> dict[str, Any]:
    if len(tokens) < 2:
        _die("usage: maverick core {cli|mcp} {list|inspect|run|call} ...")
    surface, operation = tokens[0], tokens[1]
    options, remaining = _split_wrapper_options(tokens[2:])
    workspace_id = _workspace_id(options, state.repository_root, trusted_context=trusted_context)
    if surface == "cli":
        return _run_core_cli(operation, remaining, options=options, workspace_id=workspace_id, state=state, trusted_context=trusted_context)
    if surface == "mcp":
        return _run_core_mcp(operation, remaining, options=options, workspace_id=workspace_id, state=state, trusted_context=trusted_context)
    _die("core surface must be `cli` or `mcp`")


def _run_app(tokens: list[str], *, state, trusted_context: CliInvocationContext | None = None) -> dict[str, Any]:
    if not tokens:
        _die("usage: maverick app <app_id> {cli|mcp|frontend} ...")
    if len(tokens) >= 3 and tokens[1] == "frontend":
        app_id, _surface, operation = tokens[0], tokens[1], tokens[2]
        options, remaining = _split_wrapper_options(tokens[3:])
        workspace_id = _workspace_id(options, state.repository_root, trusted_context=trusted_context)
        return _run_app_frontend(
            app_id,
            operation,
            remaining,
            options=options,
            workspace_id=workspace_id,
            state=state,
            trusted_context=trusted_context,
        )
    if len(tokens) < 3:
        _die("usage: maverick app <app_id> {cli|mcp|frontend} ...")
    app_id, surface, operation = tokens[0], tokens[1], tokens[2]
    options, remaining = _split_wrapper_options(tokens[3:])
    workspace_id = _workspace_id(options, state.repository_root, trusted_context=trusted_context)
    if surface == "cli":
        return _run_app_cli(app_id, operation, remaining, options=options, workspace_id=workspace_id, state=state, trusted_context=trusted_context)
    if surface == "mcp":
        return _run_app_mcp(app_id, operation, remaining, options=options, workspace_id=workspace_id, state=state, trusted_context=trusted_context)
    _die("app surface must be `cli`, `mcp`, or `frontend`")


def _run_app_frontend(
    app_id: str,
    operation: str,
    tokens: list[str],
    *,
    options: dict[str, str],
    workspace_id: str,
    state,
    trusted_context: CliInvocationContext | None = None,
) -> dict[str, Any]:
    if operation != "build" or tokens:
        _die(f"usage: maverick app {app_id} frontend build --json")
    return run_core_cli_command(
        command_id=f"app.{app_id}.frontend.build",
        context=_cli_context(options, workspace_id, trusted_context=trusted_context, default_caller_kind="operator", default_effective_mode="full-access"),
        app_store=state.app_store,
        identity_store=state.identity_store,
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
