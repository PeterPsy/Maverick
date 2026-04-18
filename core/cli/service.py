"""Service helpers for the platform-managed CLI surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationContext, CliInvocationPolicy
from core.cli.runner import CliRunner


def _core_command_specs() -> list[tuple[CliCommandDefinition, Any]]:
    def _workspace_current_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return {
            "command_id": "core.workspaces.current",
            "workspace_id": context.workspace_id,
            "caller_kind": context.caller_kind,
            "arguments": arguments,
        }

    def _runtime_status_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return {
            "command_id": "core.runtime.status",
            "workspace_id": context.workspace_id,
            "effective_mode": context.effective_mode,
            "arguments": arguments,
        }

    def _providers_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return {
            "command_id": "core.providers.list",
            "caller_kind": context.caller_kind,
            "arguments": arguments,
        }

    return [
        (
            CliCommandDefinition(
                command_id="core.workspaces.current",
                path_segments=["core", "workspaces", "current"],
                description="Inspect the current trusted workspace context.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="workspaces",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(
                    operator_only=False,
                    sandbox_agent_allowed=True,
                    requires_workspace_context=True,
                    requires_full_access=False,
                ),
                entrypoint_path=None,
            ),
            _workspace_current_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.runtime.status",
                path_segments=["core", "runtime", "status"],
                description="Inspect runtime status for the active workspace.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="runtime",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(
                    operator_only=False,
                    sandbox_agent_allowed=True,
                    requires_workspace_context=True,
                    requires_full_access=False,
                ),
                entrypoint_path=None,
            ),
            _runtime_status_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.providers.list",
                path_segments=["core", "providers", "list"],
                description="Inspect configured provider definitions.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="providers",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(
                    operator_only=True,
                    sandbox_agent_allowed=False,
                    requires_workspace_context=False,
                    requires_full_access=False,
                ),
                entrypoint_path=None,
            ),
            _providers_list_handler,
        ),
    ]


def _workspace_app_command_specs(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
) -> list[tuple[CliCommandDefinition, Any]]:
    specs: list[tuple[CliCommandDefinition, Any]] = []
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        if not parsed.contract.capabilities.cli_commands:
            continue
        if parsed.contract.entrypoints.cli is None:
            raise ValueError(
                f"App `{parsed.app_id}` declares CLI commands but no CLI entrypoint in its contract."
            )
        entrypoint_path = str((source_root / parsed.contract.entrypoints.cli).resolve())
        for command_name in parsed.contract.capabilities.cli_commands:
            command_id = f"app.{parsed.app_id}.{command_name}"

            def _handler(
                arguments: dict[str, Any],
                context: CliInvocationContext,
                *,
                _command_id: str = command_id,
                _app_id: str = parsed.app_id,
                _entrypoint_path: str = entrypoint_path,
            ) -> dict[str, Any]:
                return {
                    "command_id": _command_id,
                    "workspace_id": context.workspace_id,
                    "app_id": _app_id,
                    "entrypoint_path": _entrypoint_path,
                    "arguments": arguments,
                }

            specs.append(
                (
                    CliCommandDefinition(
                        command_id=command_id,
                        path_segments=["app", parsed.app_id, command_name],
                        description=f"Workspace app CLI command `{command_name}` for `{parsed.app_id}`.",
                        argument_schema={"type": "object"},
                        owner_kind="app",
                        owner_id=parsed.app_id,
                        workspace_id=workspace_id,
                        exposure_scope="workspace_enabled_app",
                        invocation_policy=CliInvocationPolicy(
                            operator_only=False,
                            sandbox_agent_allowed=True,
                            requires_workspace_context=True,
                            requires_full_access=False,
                        ),
                        entrypoint_path=entrypoint_path,
                    ),
                    _handler,
                )
            )
    return specs


def build_core_cli_registry(
    *,
    app_store: AppStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> CliCommandRegistry:
    """Build the platform-managed CLI registry for core and enabled app commands."""
    registry = CliCommandRegistry()
    for definition, handler in _core_command_specs():
        registry.register_command(definition, handler)
    if app_store is not None and workspace_id is not None:
        for definition, handler in _workspace_app_command_specs(app_store, workspace_id=workspace_id, start_path=start_path):
            registry.register_command(definition, handler)
    return registry


def list_core_cli_commands(
    *,
    app_store: AppStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> list[CliCommandDefinition]:
    """List visible CLI commands for the requested workspace context."""
    return build_core_cli_registry(app_store=app_store, workspace_id=workspace_id, start_path=start_path).list_commands()


def run_core_cli_command(
    *,
    command_id: str,
    context: CliInvocationContext,
    arguments: dict[str, Any] | None = None,
    app_store: AppStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> dict[str, Any]:
    """Run one visible CLI command under a trusted invocation context."""
    registry = build_core_cli_registry(app_store=app_store, workspace_id=workspace_id, start_path=start_path)
    return CliRunner(registry).run_command(command_id=command_id, arguments=arguments, context=context)
