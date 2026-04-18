"""Service helpers for the platform-managed CLI surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationContext, CliInvocationPolicy
from core.cli.runner import CliRunner
from core.observability.service import record_platform_audit, record_platform_event
from core.recovery.service import (
    execute_session_restart,
    record_app_health,
    record_failed_start,
    record_provider_health,
    record_runtime_health,
    recovery_status,
)
from core.recovery.store import RecoveryStore
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.store import RuntimeStore
from core.secrets.service import (
    create_platform_secret,
    disable_platform_secret,
    revoke_platform_secret,
    rotate_platform_secret,
)
from core.secrets.store import SecretStore
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.store import WorkspaceStore


def _core_command_specs(
    *,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
) -> list[tuple[CliCommandDefinition, Any]]:
    def _audit(
        action: str,
        detail: str,
        payload: dict[str, Any],
        *,
        workspace_id: str | None = None,
        provider_id: str | None = None,
        runtime_session_id: str | None = None,
    ) -> None:
        if observability_store is None:
            return
        record_platform_audit(
            observability_store,
            action=action,
            status="succeeded",
            source_domain="cli",
            detail=detail,
            workspace_id=workspace_id,
            provider_id=provider_id,
            runtime_session_id=runtime_session_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type=action,
            event_plane="platform" if runtime_session_id is None else "runtime",
            source_domain="cli",
            workspace_id=workspace_id,
            provider_id=provider_id,
            runtime_session_id=runtime_session_id,
            payload=payload,
        )

    def _workspace_current_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if workspace_store is None or context.workspace_id is None:
            return {"workspace_id": context.workspace_id, "workspace": None}
        workspace = workspace_store.get_workspace(context.workspace_id)
        return {
            "command_id": "core.workspaces.current",
            "workspace_id": context.workspace_id,
            "workspace": {
                "workspace_id": workspace.workspace_id,
                "name": workspace.name,
                "status": workspace.status,
            },
        }

    def _runtime_status_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if runtime_store is None or context.workspace_id is None:
            return {"workspace_id": context.workspace_id, "sessions": []}
        return {
            "command_id": "core.runtime.status",
            "workspace_id": context.workspace_id,
            "sessions": [
                {
                    "session_id": item.session_id,
                    "agent_id": item.agent_id,
                    "status": item.status,
                    "effective_mode": item.effective_mode,
                }
                for item in runtime_store.list_sessions(context.workspace_id)
            ],
        }

    def _providers_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"providers": []}
        return {
            "command_id": "core.providers.list",
            "providers": [
                {
                    "provider_id": item.provider_id,
                    "label": item.label,
                    "kind": item.kind,
                    "status": item.status,
                }
                for item in provider_store.list_provider_definitions()
            ],
        }

    def _secrets_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"secrets": []}
        return {
            "command_id": "core.secrets.list",
            "secrets": [
                {
                    "secret_id": item.secret_id,
                    "alias": item.alias,
                    "label": item.label,
                    "status": item.status,
                }
                for item in secret_store.list_secrets()
            ],
        }

    def _secret_bindings_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"bindings": []}
        workspace_id = arguments.get("workspace_id") or context.workspace_id
        return {
            "command_id": "core.secrets.bindings.list",
            "bindings": [
                {
                    "binding_id": item.binding_id,
                    "scope": item.scope,
                    "workspace_id": item.workspace_id,
                    "app_id": item.app_id,
                    "provider_id": item.provider_id,
                    "logical_name": item.logical_name,
                    "secret_ref": item.secret_ref,
                    "status": item.status,
                }
                for item in secret_store.list_secret_bindings(
                    workspace_id=workspace_id,
                    app_id=arguments.get("app_id"),
                    provider_id=arguments.get("provider_id"),
                )
            ],
        }

    def _secret_create_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"created": False}
        secret = create_platform_secret(
            secret_store,
            label=str(arguments["label"]),
            raw_value=str(arguments["raw_value"]),
            alias=None if arguments.get("alias") is None else str(arguments["alias"]),
            description=None if arguments.get("description") is None else str(arguments["description"]),
        )
        result = {
            "command_id": "core.secrets.create",
            "created": True,
            "secret": {"secret_id": secret.secret_id, "alias": secret.alias, "label": secret.label, "status": secret.status},
        }
        _audit("core.secrets.create", f"Created platform secret `{secret.secret_id}`.", {"secret_id": secret.secret_id, "alias": secret.alias})
        return result

    def _secret_rotate_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"rotated": False}
        secret = rotate_platform_secret(
            secret_store,
            secret_id=str(arguments["secret_id"]),
            raw_value=str(arguments["raw_value"]),
        )
        result = {
            "command_id": "core.secrets.rotate",
            "rotated": True,
            "secret": {
                "secret_id": secret.secret_id,
                "alias": secret.alias,
                "label": secret.label,
                "status": secret.status,
            },
        }
        _audit("core.secrets.rotate", f"Rotated platform secret `{secret.secret_id}`.", {"secret_id": secret.secret_id})
        return result

    def _secret_disable_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"disabled": False}
        secret = disable_platform_secret(secret_store, secret_id=str(arguments["secret_id"]))
        result = {
            "command_id": "core.secrets.disable",
            "disabled": True,
            "secret_id": secret.secret_id,
            "status": secret.status,
        }
        _audit("core.secrets.disable", f"Disabled platform secret `{secret.secret_id}`.", {"secret_id": secret.secret_id})
        return result

    def _secret_revoke_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"revoked": False}
        secret = revoke_platform_secret(secret_store, secret_id=str(arguments["secret_id"]))
        result = {
            "command_id": "core.secrets.revoke",
            "revoked": True,
            "secret_id": secret.secret_id,
            "status": secret.status,
        }
        _audit("core.secrets.revoke", f"Revoked platform secret `{secret.secret_id}`.", {"secret_id": secret.secret_id})
        return result

    def _recovery_status_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if recovery_store is None:
            return {"status": None}
        return {
            "command_id": "core.recovery.status",
            "status": recovery_status(
                recovery_store,
                workspace_id=arguments.get("workspace_id") or context.workspace_id,
                session_id=arguments.get("session_id"),
            ),
        }

    def _recovery_restart_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if recovery_store is None or runtime_store is None:
            return {"planned": False}
        intent, restarted = execute_session_restart(
            recovery_store,
            runtime_store=runtime_store,
            session_id=str(arguments["session_id"]),
            reason=str(arguments.get("reason") or "operator restart"),
            observability_store=observability_store,
        )
        return {
            "command_id": "core.recovery.restart",
            "executed": True,
            "intent_id": intent.intent_id,
            "action": intent.action,
            "session_id": intent.session_id,
            "runtime_status": restarted.status,
        }

    def _recovery_failed_start_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if recovery_store is None:
            return {"planned": False}
        failure, intent = record_failed_start(
            recovery_store,
            category=str(arguments["category"]),
            detail=str(arguments["detail"]),
            workspace_id=arguments.get("workspace_id") or context.workspace_id,
            session_id=arguments.get("session_id"),
            observability_store=observability_store,
        )
        return {
            "command_id": "core.recovery.failed_start",
            "planned": True,
            "failure_id": failure.failure_id,
            "intent_id": intent.intent_id,
            "action": intent.action,
        }

    def _recovery_health_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if recovery_store is None:
            return {"health": None}
        target_kind = str(arguments["target_kind"])
        if target_kind == "runtime":
            if runtime_store is None:
                return {"health": None}
            session = runtime_store.get_session(str(arguments["session_id"]))
            result = record_runtime_health(recovery_store, session=session, observability_store=observability_store)
        elif target_kind == "provider":
            if provider_registry is None:
                return {"health": None}
            result = record_provider_health(
                recovery_store,
                provider_registry=provider_registry,
                provider_id=str(arguments["provider_id"]),
                workspace_id=arguments.get("workspace_id") or context.workspace_id,
                observability_store=observability_store,
            )
        else:
            result = record_app_health(
                recovery_store,
                workspace_id=str(arguments.get("workspace_id") or context.workspace_id),
                app_id=str(arguments["app_id"]),
                is_healthy=bool(arguments["is_healthy"]),
                detail=None if arguments.get("detail") is None else str(arguments["detail"]),
                observability_store=observability_store,
            )
        return {
            "command_id": "core.recovery.health",
            "health": {"target_kind": result.target_kind, "target_id": result.target_id, "status": result.status, "detail": result.detail},
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
        (
            CliCommandDefinition(
                command_id="core.secrets.list",
                path_segments=["core", "secrets", "list"],
                description="Inspect platform secret metadata without raw values.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secrets_list_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.secrets.bindings.list",
                path_segments=["core", "secrets", "bindings", "list"],
                description="Inspect secret binding metadata without raw values.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_bindings_list_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.secrets.create",
                path_segments=["core", "secrets", "create"],
                description="Create one platform secret without exposing its raw value in the result.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_create_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.secrets.rotate",
                path_segments=["core", "secrets", "rotate"],
                description="Rotate one platform secret without exposing the raw value.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_rotate_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.secrets.disable",
                path_segments=["core", "secrets", "disable"],
                description="Disable one platform secret.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_disable_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.secrets.revoke",
                path_segments=["core", "secrets", "revoke"],
                description="Revoke one platform secret and remove its raw value.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_revoke_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.recovery.status",
                path_segments=["core", "recovery", "status"],
                description="Inspect recovery status for one workspace or runtime session.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="recovery",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _recovery_status_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.recovery.restart",
                path_segments=["core", "recovery", "restart"],
                description="Execute one runtime restart recovery action when allowed.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="recovery",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _recovery_restart_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.recovery.failed_start",
                path_segments=["core", "recovery", "failed-start"],
                description="Record one failed-start diagnosis and plan recovery.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="recovery",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _recovery_failed_start_handler,
        ),
        (
            CliCommandDefinition(
                command_id="core.recovery.health",
                path_segments=["core", "recovery", "health"],
                description="Run one recovery health probe on demand.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="recovery",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _recovery_health_handler,
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
                _source_root: Path = source_root,
            ) -> dict[str, Any]:
                return run_json_entrypoint(
                    _entrypoint_path,
                    payload={
                        "surface": "cli",
                        "command_id": _command_id,
                        "workspace_id": context.workspace_id,
                        "agent_id": context.agent_id,
                        "effective_mode": context.effective_mode,
                        "app_id": _app_id,
                        "arguments": arguments,
                    },
                    cwd=_source_root,
                )

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
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> CliCommandRegistry:
    """Build the platform-managed CLI registry for core and enabled app commands."""
    registry = CliCommandRegistry()
    for definition, handler in _core_command_specs(
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
    ):
        registry.register_command(definition, handler)
    if app_store is not None and workspace_id is not None:
        for definition, handler in _workspace_app_command_specs(app_store, workspace_id=workspace_id, start_path=start_path):
            registry.register_command(definition, handler)
    return registry


def list_core_cli_commands(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> list[CliCommandDefinition]:
    """List visible CLI commands for the requested workspace context."""
    return build_core_cli_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        workspace_id=workspace_id,
        start_path=start_path,
    ).list_commands()


def run_core_cli_command(
    *,
    command_id: str,
    context: CliInvocationContext,
    arguments: dict[str, Any] | None = None,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> dict[str, Any]:
    """Run one visible CLI command under a trusted invocation context."""
    registry = build_core_cli_registry(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        workspace_id=workspace_id,
        start_path=start_path,
    )
    return CliRunner(registry).run_command(command_id=command_id, arguments=arguments, context=context)
