"""Core-owned CLI commands for the official Maverick App SDK."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.packaging import package_app_source
from core.app_sdk.service import app_sdk_status, create_app_source, install_local_app, register_local_app, validate_app_source
from core.apps.store import AppStore
from core.cli.models import CliCommandDefinition, CliInvocationContext, CliInvocationPolicy


APP_SDK_POLICY = CliInvocationPolicy(
    operator_only=True,
    required_platform_role=None,
    sandbox_agent_allowed=False,
    requires_workspace_context=True,
    requires_full_access=False,
)


def app_sdk_command_specs(
    *,
    app_store: AppStore | None,
    observability_store=None,
    start_path: Path | None = None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build core-owned app SDK command specs."""
    return [
        (_definition("create", "Generate a Maverick app source tree from an SDK template."), _create_handler(start_path)),
        (_definition("validate", "Validate a Maverick app source tree."), _validate_handler(start_path)),
        (_definition("register-local", "Register a workspace-local Maverick app project."), _register_handler(app_store, start_path)),
        (_definition("install-local", "Install a registered workspace-local Maverick app."), _install_handler(app_store, observability_store, start_path)),
        (_definition("status", "Inspect SDK app source, registration, and installation state."), _status_handler(app_store, start_path)),
        (_definition("package", "Package a valid Maverick app source tree."), _package_handler()),
    ]


def _definition(action: str, description: str) -> CliCommandDefinition:
    return CliCommandDefinition(
        command_id=f"core.app-sdk.{action}",
        path_segments=["maverick", "app", action],
        description=description,
        argument_schema={"type": "object"},
        owner_kind="core",
        owner_id="app-sdk",
        workspace_id=None,
        exposure_scope="core_global",
        invocation_policy=APP_SDK_POLICY,
        entrypoint_path=None,
    )


def _workspace_id(arguments: dict[str, Any], context: CliInvocationContext) -> str:
    return str(arguments.get("workspace_id") or context.workspace_id or "").strip()


def _create_handler(start_path: Path | None):
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        request = AppSdkCreateRequest(
            app_id=str(arguments["app_id"]),
            template_id=arguments.get("template_id", "minimal"),
            target_kind=arguments.get("target_kind", "workspace_local"),
            workspace_id=str(arguments.get("workspace_id") or context.workspace_id or ""),
            name=arguments.get("name"),
            description=arguments.get("description"),
            publisher=str(arguments.get("publisher") or "workspace"),
            version=str(arguments.get("version") or "0.1.0"),
            overwrite=bool(arguments.get("overwrite", False)),
            entities=arguments.get("entities"),
        )
        return asdict(create_app_source(request, start_path=start_path))

    return _handler


def _validate_handler(start_path: Path | None):
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        app_root = arguments.get("app_root")
        if not app_root:
            app_id = str(arguments["app_id"])
            app_root = str(Path(start_path or Path.cwd()) / "workspaces" / _workspace_id(arguments, context) / "apps" / app_id)
        return asdict(validate_app_source(app_root))

    return _handler


def _register_handler(app_store: AppStore | None, start_path: Path | None):
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if app_store is None:
            raise RuntimeError("App SDK register-local requires an app store.")
        return register_local_app(
            app_store,
            workspace_id=_workspace_id(arguments, context),
            app_id=str(arguments["app_id"]),
            start_path=start_path,
        )

    return _handler


def _install_handler(app_store: AppStore | None, observability_store, start_path: Path | None):
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if app_store is None:
            raise RuntimeError("App SDK install-local requires an app store.")
        return install_local_app(
            app_store,
            workspace_id=_workspace_id(arguments, context),
            app_id=str(arguments["app_id"]),
            start_path=start_path,
            observability_store=observability_store,
        )

    return _handler


def _status_handler(app_store: AppStore | None, start_path: Path | None):
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        return asdict(
            app_sdk_status(
                app_store,
                workspace_id=_workspace_id(arguments, context),
                app_id=str(arguments["app_id"]),
                start_path=start_path,
            )
        )

    return _handler


def _package_handler():
    def _handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        app_root = arguments.get("app_root")
        if not app_root:
            raise RuntimeError("App SDK package requires `app_root`.")
        return asdict(package_app_source(app_root, output_path=arguments.get("output_path")))

    return _handler
