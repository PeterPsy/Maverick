"""Service helpers for building the platform-managed MCP surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
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
from core.mcp.models import McpInvocationContext, McpInvocationPolicy, McpToolDefinition
from core.mcp.runner import McpRunner
from core.mcp.server import McpHostSurface, build_mcp_host_surface
from core.mcp.tool_registry import McpToolRegistry
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.store import RuntimeStore
from core.secrets.service import create_platform_secret, disable_platform_secret, revoke_platform_secret, rotate_platform_secret
from core.secrets.store import SecretStore
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths
from core.workspaces.store import WorkspaceStore


def _core_tool_specs(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    start_path: Path | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    def _audit(event_type: str, payload: dict[str, Any], *, workspace_id: str | None = None, provider_id: str | None = None, runtime_session_id: str | None = None) -> None:
        if observability_store is None:
            return
        record_platform_audit(
            observability_store,
            action=event_type,
            status="succeeded",
            source_domain="mcp",
            detail=event_type,
            workspace_id=workspace_id,
            provider_id=provider_id,
            runtime_session_id=runtime_session_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type=event_type,
            event_plane="platform" if runtime_session_id is None else "runtime",
            source_domain="mcp",
            workspace_id=workspace_id,
            provider_id=provider_id,
            runtime_session_id=runtime_session_id,
            payload=payload,
        )
    def _workspace_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if workspace_store is None:
            return {"items": []}
        return {
            "items": [
                {
                    "workspace_id": item.workspace_id,
                    "name": item.name,
                    "status": item.status,
                }
                for item in workspace_store.list_workspaces()
            ]
        }

    def _runtime_status_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if runtime_store is None:
            return {"workspace_id": context.workspace_id, "sessions": []}
        workspace_id = arguments.get("workspace_id") or context.workspace_id
        if workspace_id is None:
            return {"workspace_id": None, "sessions": []}
        return {
            "workspace_id": workspace_id,
            "sessions": [
                {
                    "session_id": item.session_id,
                    "agent_id": item.agent_id,
                    "status": item.status,
                    "effective_mode": item.effective_mode,
                }
                for item in runtime_store.list_sessions(workspace_id)
            ],
        }

    def _providers_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"items": []}
        return {
            "items": [
                {
                    "provider_id": item.provider_id,
                    "label": item.label,
                    "kind": item.kind,
                    "status": item.status,
                }
                for item in provider_store.list_provider_definitions()
            ]
        }

    def _secrets_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"items": []}
        return {
            "items": [
                {
                    "secret_id": item.secret_id,
                    "alias": item.alias,
                    "label": item.label,
                    "status": item.status,
                }
                for item in secret_store.list_secrets()
            ]
        }

    def _secret_create_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"created": False}
        secret = create_platform_secret(
            secret_store,
            label=str(arguments["label"]),
            raw_value=str(arguments["raw_value"]),
            alias=None if arguments.get("alias") is None else str(arguments["alias"]),
            description=None if arguments.get("description") is None else str(arguments["description"]),
        )
        _audit("core.secrets.create", {"secret_id": secret.secret_id, "alias": secret.alias})
        return {"created": True, "secret": {"secret_id": secret.secret_id, "alias": secret.alias, "label": secret.label, "status": secret.status}}

    def _secret_rotate_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"rotated": False}
        secret = rotate_platform_secret(
            secret_store,
            secret_id=str(arguments["secret_id"]),
            raw_value=str(arguments["raw_value"]),
        )
        _audit("core.secrets.rotate", {"secret_id": secret.secret_id})
        return {"rotated": True, "secret_id": secret.secret_id, "status": secret.status}

    def _secret_disable_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"disabled": False}
        secret = disable_platform_secret(secret_store, secret_id=str(arguments["secret_id"]))
        _audit("core.secrets.disable", {"secret_id": secret.secret_id})
        return {"disabled": True, "secret_id": secret.secret_id, "status": secret.status}

    def _secret_revoke_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"revoked": False}
        secret = revoke_platform_secret(secret_store, secret_id=str(arguments["secret_id"]))
        _audit("core.secrets.revoke", {"secret_id": secret.secret_id})
        return {"revoked": True, "secret_id": secret.secret_id, "status": secret.status}

    def _recovery_status_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if recovery_store is None:
            return {"status": None}
        return {
            "status": recovery_status(
                recovery_store,
                workspace_id=arguments.get("workspace_id") or context.workspace_id,
                session_id=arguments.get("session_id"),
            )
        }

    def _recovery_restart_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if recovery_store is None or runtime_store is None:
            return {"executed": False}
        intent, restarted = execute_session_restart(
            recovery_store,
            runtime_store=runtime_store,
            session_id=str(arguments["session_id"]),
            reason=str(arguments.get("reason") or "operator restart"),
            observability_store=observability_store,
        )
        return {"executed": True, "intent_id": intent.intent_id, "action": intent.action, "runtime_status": restarted.status}

    def _recovery_failed_start_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
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
        return {"planned": True, "failure_id": failure.failure_id, "intent_id": intent.intent_id, "action": intent.action}

    def _recovery_health_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
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
            if app_store is None:
                return {"health": None}
            result = record_app_health(
                recovery_store,
                app_store=app_store,
                workspace_id=str(arguments.get("workspace_id") or context.workspace_id),
                app_id=str(arguments["app_id"]),
                start_path=start_path,
                observability_store=observability_store,
            )
        return {"health": {"target_kind": result.target_kind, "target_id": result.target_id, "status": result.status, "detail": result.detail}}

    return [
        (
            McpToolDefinition(
                tool_name="core.workspaces.list",
                description="Inspect the core workspace registry.",
                input_schema={},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="workspaces",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _workspace_list_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.runtime.status",
                description="Inspect runtime session status for the active workspace.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="runtime",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(False, True, True, False),
                entrypoint_path=None,
            ),
            _runtime_status_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.providers.list",
                description="Inspect configured provider definitions and availability.",
                input_schema={},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="providers",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _providers_list_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.secrets.list",
                description="Inspect platform secret metadata without raw values.",
                input_schema={},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secrets_list_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.secrets.create",
                description="Create one platform secret without exposing the raw value in the result.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_create_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.secrets.rotate",
                description="Rotate one platform secret without exposing the raw value.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_rotate_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.secrets.disable",
                description="Disable one platform secret.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_disable_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.secrets.revoke",
                description="Revoke one platform secret and remove its raw value.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="secrets",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _secret_revoke_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.recovery.status",
                description="Inspect recovery status for one workspace or runtime session.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="recovery",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _recovery_status_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.recovery.restart",
                description="Execute one runtime restart recovery action when allowed.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="recovery",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _recovery_restart_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.recovery.failed_start",
                description="Record one failed-start diagnosis and plan recovery.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="recovery",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _recovery_failed_start_handler,
        ),
        (
            McpToolDefinition(
                tool_name="core.recovery.health",
                description="Run one recovery health probe on demand.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                owner_kind="core",
                owner_id="recovery",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(True, False, False, False),
                entrypoint_path=None,
            ),
            _recovery_health_handler,
        ),
    ]


def _workspace_app_tool_definitions(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    definitions: list[tuple[McpToolDefinition, Any]] = []
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        if not parsed.contract.capabilities.mcp_tools:
            continue
        if parsed.contract.entrypoints.mcp is None:
            raise ValueError(
                f"App `{parsed.app_id}` declares MCP tools but no MCP entrypoint in its contract."
            )
        entrypoint_path = str((source_root / parsed.contract.entrypoints.mcp).resolve())
        paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
        for tool_name in parsed.contract.capabilities.mcp_tools:
            hosted_tool_name = f"app.{parsed.app_id}.{tool_name}"
            def _handler(
                arguments: dict[str, Any],
                context: McpInvocationContext,
                *,
                _entrypoint_path: str = entrypoint_path,
                _tool_name: str = tool_name,
                _workspace_id: str = workspace_id,
                _source_root: Path = source_root,
                _app_id: str = parsed.app_id,
                _data_root: str = binding.data_root,
                _workspace_root: str = str(paths.root),
                _uploaded_storage_root: str = str(paths.uploaded_storage),
                _generated_storage_root: str = str(paths.generated_storage),
            ) -> dict[str, Any]:
                return run_json_entrypoint(
                    _entrypoint_path,
                    payload={
                        "surface": "mcp",
                        "tool_name": _tool_name,
                        "workspace_id": _workspace_id,
                        "app_id": _app_id,
                        "workspace_root": _workspace_root,
                        "data_root": _data_root,
                        "uploaded_storage_root": _uploaded_storage_root,
                        "generated_storage_root": _generated_storage_root,
                        "arguments": arguments,
                    },
                    cwd=_source_root,
                )

            definitions.append(
                (
                    McpToolDefinition(
                        tool_name=hosted_tool_name,
                        description=f"App MCP tool exposed by `{parsed.app_id}`.",
                        input_schema={"type": "object"},
                        output_schema={"type": "object"},
                        owner_kind="app",
                        owner_id=parsed.app_id,
                        workspace_id=workspace_id,
                        exposure_scope="workspace_enabled_app",
                        invocation_policy=McpInvocationPolicy(
                            operator_only=False,
                            sandbox_agent_allowed=True,
                            requires_workspace_context=True,
                            requires_full_access=False,
                        ),
                        entrypoint_path=entrypoint_path,
                    ),
                    lambda arguments, context, _handler=_handler: _handler(arguments, context),
                )
            )
    return definitions


def build_core_mcp_registry(
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
) -> McpToolRegistry:
    """Build the platform-managed MCP registry for core and enabled app tools."""
    registry = McpToolRegistry()
    for definition, handler in _core_tool_specs(
        app_store=app_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        start_path=start_path,
    ):
        registry.register_tool(definition, handler)
    if app_store is not None and workspace_id is not None:
        for definition, handler in _workspace_app_tool_definitions(app_store, workspace_id=workspace_id, start_path=start_path):
            registry.register_tool(definition, handler)
    return registry


def build_workspace_mcp_surface(
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
    transport: str = "stdio",
) -> McpHostSurface:
    """Build one MCP host surface for the requested workspace context."""
    registry = build_core_mcp_registry(
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
    return build_mcp_host_surface(registry, transport=transport)


def list_mcp_tools(
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
) -> list[McpToolDefinition]:
    """List visible MCP tools for the requested workspace context."""
    return build_core_mcp_registry(
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
    ).list_tools()


def call_mcp_tool(
    *,
    tool_name: str,
    context: McpInvocationContext,
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
    """Invoke one visible MCP tool under a trusted invocation context."""
    registry = build_core_mcp_registry(
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
    return McpRunner(registry).call_tool(tool_name=tool_name, arguments=arguments or {}, context=context)
