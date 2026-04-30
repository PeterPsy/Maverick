"""Core-owned CLI commands for workspace app lifecycle operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.errors import AppHostingError
from core.apps.dependencies import resolve_app_dependencies, save_app_dependency_selection
from core.apps.frontend_build import app_supports_frontend_build, build_workspace_app_frontend
from core.apps.models import AppSourceRecord, WorkspaceLocalAppProjectRecord
from core.apps.service import delete_workspace_local_app_project, install_store_app, install_workspace_local_app, uninstall_workspace_app
from core.apps.store import AppStore
from core.apps.workspace_local_discovery import sync_workspace_local_app_projects
from core.cli.core_command_helpers import record_cli_audit
from core.cli.models import CliCommandDefinition, CliInvocationContext, CliInvocationPolicy


APP_MANAGEMENT = CliInvocationPolicy(
    operator_only=False,
    required_platform_role=None,
    sandbox_agent_allowed=True,
    requires_workspace_context=True,
    requires_full_access=False,
)

APP_FRONTEND_BUILD = CliInvocationPolicy(
    operator_only=False,
    required_platform_role=None,
    sandbox_agent_allowed=False,
    requires_workspace_context=True,
    requires_full_access=False,
)

APP_WORKSPACE_READ = CliInvocationPolicy(
    operator_only=False,
    required_platform_role=None,
    sandbox_agent_allowed=True,
    requires_workspace_context=True,
    requires_full_access=False,
)


def app_lifecycle_command_specs(
    *,
    app_store: AppStore | None,
    workspace_id: str | None,
    start_path: Path | None = None,
    observability_store=None,
    app_event_bus=None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build per-app lifecycle CLI commands for known app sources and workspace-local projects."""
    if app_store is None or workspace_id is None:
        return []
    sync_workspace_local_app_projects(app_store, workspace_id=workspace_id, start_path=start_path)
    sources_by_app = _source_records_by_app(app_store.list_app_sources())
    projects_by_app = {
        project.app_id: project
        for project in app_store.list_workspace_local_app_projects(workspace_id)
    }
    bindings_by_app = {
        binding.app_id: binding
        for binding in app_store.list_workspace_app_bindings(workspace_id)
    }
    app_ids = sorted({*sources_by_app, *projects_by_app, *bindings_by_app})
    specs: list[tuple[CliCommandDefinition, Any]] = []
    for app_id in app_ids:
        if app_id in sources_by_app or app_id in projects_by_app:
            specs.append(
                _install_command(
                    app_store,
                    app_id=app_id,
                    sources=sources_by_app.get(app_id, []),
                    project=projects_by_app.get(app_id),
                    observability_store=observability_store,
                    workspace_id=workspace_id,
                    start_path=start_path,
                )
            )
        if app_id in bindings_by_app:
            specs.append(
                _dependencies_command(
                    app_store,
                    app_id=app_id,
                    workspace_id=workspace_id,
                    start_path=start_path,
                )
            )
            specs.append(
                _dependency_set_command(
                    app_store,
                    app_id=app_id,
                    observability_store=observability_store,
                    workspace_id=workspace_id,
                    start_path=start_path,
                )
            )
            specs.append(
                _uninstall_command(
                    app_store,
                    app_id=app_id,
                    observability_store=observability_store,
                    workspace_id=workspace_id,
                )
            )
            binding = bindings_by_app[app_id]
            if app_supports_frontend_build(app_store, binding=binding, start_path=start_path):
                specs.append(
                    _frontend_build_command(
                        app_store,
                        app_id=app_id,
                        app_event_bus=app_event_bus,
                        observability_store=observability_store,
                        workspace_id=workspace_id,
                        start_path=start_path,
                    )
                )
        if app_id in projects_by_app:
            specs.append(
                _remove_command(
                    app_store,
                    app_id=app_id,
                    observability_store=observability_store,
                    workspace_id=workspace_id,
                    start_path=start_path,
                )
            )
    return specs


def _source_records_by_app(sources: list[AppSourceRecord]) -> dict[str, list[AppSourceRecord]]:
    by_app: dict[str, list[AppSourceRecord]] = {}
    for source in sources:
        by_app.setdefault(source.app_id, []).append(source)
    for app_sources in by_app.values():
        app_sources.sort(key=lambda source: (source.version, source.source_id), reverse=True)
    return by_app


def _command_definition(*, app_id: str, action: str, description: str, workspace_id: str) -> CliCommandDefinition:
    return CliCommandDefinition(
        command_id=f"app.{app_id}.{action}",
        path_segments=["app", app_id, action],
        description=description,
        argument_schema={"type": "object"},
        owner_kind="app",
        owner_id=app_id,
        workspace_id=workspace_id,
        exposure_scope="core_global",
        invocation_policy=APP_MANAGEMENT,
        entrypoint_path=None,
    )


def _frontend_build_command_definition(*, app_id: str, description: str, workspace_id: str) -> CliCommandDefinition:
    return CliCommandDefinition(
        command_id=f"app.{app_id}.frontend.build",
        path_segments=["app", app_id, "frontend.build"],
        description=description,
        argument_schema={"type": "object"},
        owner_kind="app",
        owner_id=app_id,
        workspace_id=workspace_id,
        exposure_scope="core_global",
        invocation_policy=APP_FRONTEND_BUILD,
        entrypoint_path=None,
    )

def _dependency_status_command_definition(*, app_id: str, description: str, workspace_id: str) -> CliCommandDefinition:
    return CliCommandDefinition(
        command_id=f"app.{app_id}.dependencies",
        path_segments=["app", app_id, "dependencies"],
        description=description,
        argument_schema={"type": "object"},
        owner_kind="app",
        owner_id=app_id,
        workspace_id=workspace_id,
        exposure_scope="core_global",
        invocation_policy=APP_WORKSPACE_READ,
        entrypoint_path=None,
    )


def _dependency_set_command_definition(*, app_id: str, description: str, workspace_id: str) -> CliCommandDefinition:
    return CliCommandDefinition(
        command_id=f"app.{app_id}.dependencies.set",
        path_segments=["app", app_id, "dependencies.set"],
        description=description,
        argument_schema={
            "type": "object",
            "properties": {
                "alias": {"type": "string"},
                "provider_app_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["alias"],
        },
        owner_kind="app",
        owner_id=app_id,
        workspace_id=workspace_id,
        exposure_scope="core_global",
        invocation_policy=APP_MANAGEMENT,
        entrypoint_path=None,
    )


def _target_workspace_id(arguments: dict[str, Any], context: CliInvocationContext, fallback: str) -> str:
    return str(arguments.get("workspace_id") or context.workspace_id or fallback).strip()


def _install_command(
    app_store: AppStore,
    *,
    app_id: str,
    sources: list[AppSourceRecord],
    project: WorkspaceLocalAppProjectRecord | None,
    observability_store,
    workspace_id: str,
    start_path: Path | None,
) -> tuple[CliCommandDefinition, Any]:
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        target_workspace_id = _target_workspace_id(arguments, context, workspace_id)
        source_id = str(arguments.get("source_id") or "").strip()
        try:
            if source_id:
                binding = install_store_app(
                    app_store,
                    source_id=source_id,
                    workspace_id=target_workspace_id,
                    start_path=start_path,
                    observability_store=observability_store,
                )
            elif project is not None and project.workspace_id == target_workspace_id:
                binding = install_workspace_local_app(
                    app_store,
                    workspace_id=target_workspace_id,
                    app_id=app_id,
                    start_path=start_path,
                    observability_store=observability_store,
                )
            elif sources:
                binding = install_store_app(
                    app_store,
                    source_id=sources[0].source_id,
                    workspace_id=target_workspace_id,
                    start_path=start_path,
                    observability_store=observability_store,
                )
            else:
                raise AppHostingError(f"No install source is available for app `{app_id}`.")
        except AppHostingError:
            raise
        payload = {
            "status": "installed",
            "workspace_id": binding.workspace_id,
            "app_id": binding.app_id,
            "binding_status": binding.status,
            "active_version": binding.active_version,
            "source_kind": binding.source_kind,
            "source_record_id": binding.source_record_id,
        }
        record_cli_audit(
            observability_store,
            action="cli.app.install",
            detail=f"Installed app `{app_id}` through CLI.",
            workspace_id=binding.workspace_id,
            payload=payload,
        )
        return payload

    return (
        _command_definition(
            app_id=app_id,
            action="install",
            description=f"Install app `{app_id}` into the current workspace.",
            workspace_id=workspace_id,
        ),
        _handler,
    )


def _dependencies_command(
    app_store: AppStore,
    *,
    app_id: str,
    workspace_id: str,
    start_path: Path | None,
) -> tuple[CliCommandDefinition, Any]:
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        target_workspace_id = _target_workspace_id(arguments, context, workspace_id)
        return resolve_app_dependencies(
            app_store,
            workspace_id=target_workspace_id,
            consumer_app_id=app_id,
            start_path=start_path,
        )

    return (
        _dependency_status_command_definition(
            app_id=app_id,
            description=f"Inspect cross-app dependency resolution for app `{app_id}`.",
            workspace_id=workspace_id,
        ),
        _handler,
    )


def _dependency_set_command(
    app_store: AppStore,
    *,
    app_id: str,
    observability_store,
    workspace_id: str,
    start_path: Path | None,
) -> tuple[CliCommandDefinition, Any]:
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        target_workspace_id = _target_workspace_id(arguments, context, workspace_id)
        alias = str(arguments.get("alias") or "").strip()
        provider_app_ids = arguments.get("provider_app_ids")
        if not isinstance(provider_app_ids, list):
            provider_app_ids = []
        payload = save_app_dependency_selection(
            app_store,
            workspace_id=target_workspace_id,
            consumer_app_id=app_id,
            alias=alias,
            provider_app_ids=[str(item) for item in provider_app_ids],
            start_path=start_path,
        )
        record_cli_audit(
            observability_store,
            action="cli.app.dependencies.set",
            detail=f"Configured dependency alias `{alias}` for app `{app_id}` through CLI.",
            workspace_id=target_workspace_id,
            payload={"app_id": app_id, "alias": alias, "provider_app_ids": provider_app_ids},
        )
        return payload

    return (
        _dependency_set_command_definition(
            app_id=app_id,
            description=f"Configure a cross-app dependency provider selection for app `{app_id}`.",
            workspace_id=workspace_id,
        ),
        _handler,
    )


def _uninstall_command(
    app_store: AppStore,
    *,
    app_id: str,
    observability_store,
    workspace_id: str,
) -> tuple[CliCommandDefinition, Any]:
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        target_workspace_id = _target_workspace_id(arguments, context, workspace_id)
        uninstall_workspace_app(
            app_store,
            workspace_id=target_workspace_id,
            app_id=app_id,
            observability_store=observability_store,
        )
        payload = {"status": "uninstalled", "workspace_id": target_workspace_id, "app_id": app_id}
        record_cli_audit(
            observability_store,
            action="cli.app.uninstall",
            detail=f"Uninstalled app `{app_id}` through CLI.",
            workspace_id=target_workspace_id,
            payload=payload,
        )
        return payload

    return (
        _command_definition(
            app_id=app_id,
            action="uninstall",
            description=f"Uninstall app `{app_id}` from the current workspace while preserving app data.",
            workspace_id=workspace_id,
        ),
        _handler,
    )


def _remove_command(
    app_store: AppStore,
    *,
    app_id: str,
    observability_store,
    workspace_id: str,
    start_path: Path | None,
) -> tuple[CliCommandDefinition, Any]:
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        target_workspace_id = _target_workspace_id(arguments, context, workspace_id)
        result = delete_workspace_local_app_project(
            app_store,
            workspace_id=target_workspace_id,
            app_id=app_id,
            start_path=start_path,
            observability_store=observability_store,
        )
        payload = {"status": "removed", **result}
        record_cli_audit(
            observability_store,
            action="cli.app.remove",
            detail=f"Removed workspace-local app `{app_id}` through CLI.",
            workspace_id=target_workspace_id,
            payload=payload,
        )
        return payload

    return (
        _command_definition(
            app_id=app_id,
            action="remove",
            description=f"Remove workspace-local app `{app_id}` completely from the current workspace.",
            workspace_id=workspace_id,
        ),
        _handler,
    )


def _frontend_build_command(
    app_store: AppStore,
    *,
    app_id: str,
    app_event_bus,
    observability_store,
    workspace_id: str,
    start_path: Path | None,
) -> tuple[CliCommandDefinition, Any]:
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        target_workspace_id = _target_workspace_id(arguments, context, workspace_id)
        payload = build_workspace_app_frontend(
            app_store,
            workspace_id=target_workspace_id,
            app_id=app_id,
            start_path=start_path,
            app_event_bus=app_event_bus,
        )
        record_cli_audit(
            observability_store,
            action="cli.app.frontend.build",
            detail=f"Built frontend for app `{app_id}` through CLI.",
            workspace_id=target_workspace_id,
            payload=payload,
        )
        return payload

    return (
        _frontend_build_command_definition(
            app_id=app_id,
            description=f"Build the declared frontend artifact for app `{app_id}` and refresh mounted clients.",
            workspace_id=workspace_id,
        ),
        _handler,
    )
