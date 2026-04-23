"""App-contributed CLI command mounting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.cli.models import CliCommandDefinition, CliInvocationContext, CliInvocationPolicy
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths


def _app_command_invocation_policy(app_id: str, command_name: str) -> CliInvocationPolicy:
    if app_id == "skills" and command_name == "sync":
        return CliInvocationPolicy(
            operator_only=False,
            required_platform_role="admin",
            sandbox_agent_allowed=True,
            requires_workspace_context=True,
            requires_full_access=False,
        )
    return CliInvocationPolicy(
        operator_only=False,
        required_platform_role=None,
        sandbox_agent_allowed=True,
        requires_workspace_context=True,
        requires_full_access=False,
    )


def _workspace_app_command_specs(
    store: AppStore,
    *,
    workspace_id: str,
    app_event_bus=None,
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
        paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
        for command_name in parsed.contract.capabilities.cli_commands:
            command_id = f"app.{parsed.app_id}.{command_name}"

            def _handler(
                arguments: dict[str, Any],
                context: CliInvocationContext,
                *,
                _command_id: str = command_id,
                _app_id: str = parsed.app_id,
                _entrypoint_path: str = entrypoint_path,
                _source_root: Path = source_root,
                _data_root: str = binding.data_root,
                _workspace_root: str = str(paths.root),
                _uploaded_storage_root: str = str(paths.uploaded_storage),
                _generated_storage_root: str = str(paths.generated_storage),
                _app_event_bus=app_event_bus,
            ) -> dict[str, Any]:
                result = run_json_entrypoint(
                    _entrypoint_path,
                    payload={
                        "surface": "cli",
                        "command_id": _command_id,
                        "workspace_id": context.workspace_id,
                        "agent_id": context.agent_id,
                        "effective_mode": context.effective_mode,
                        "app_id": _app_id,
                        "workspace_root": _workspace_root,
                        "data_root": _data_root,
                        "uploaded_storage_root": _uploaded_storage_root,
                        "generated_storage_root": _generated_storage_root,
                        "arguments": arguments,
                    },
                    cwd=_source_root,
                )
                _publish_app_events(
                    _app_event_bus,
                    result,
                    workspace_id=context.workspace_id,
                    app_id=_app_id,
                )
                return result

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
                        invocation_policy=_app_command_invocation_policy(parsed.app_id, command_name),
                        entrypoint_path=entrypoint_path,
                    ),
                    _handler,
                )
            )
    return specs


def _publish_app_events(app_event_bus, result: dict[str, Any], *, workspace_id: str, app_id: str) -> None:
    if app_event_bus is None:
        return
    events = result.get("app_events", [])
    if not isinstance(events, list):
        return
    for event in events:
        if not isinstance(event, dict):
            continue
        app_event_bus.publish(
            {
                "type": str(event.get("type") or "maverick.app.data-changed"),
                "workspace_id": workspace_id,
                "owner_app_id": str(event.get("owner_app_id") or app_id),
                "resource": str(event.get("resource") or ""),
            }
        )
