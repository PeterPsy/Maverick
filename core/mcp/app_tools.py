"""App-contributed MCP tool mounting."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from typing import Any

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.apps.dependencies import resolve_app_dependencies
from core.apps.runtime_requests import apply_app_runtime_requests
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.apps.surface_descriptors import (
    AppSurfaceSecretSelector,
    app_mcp_tool_metadata,
    app_mcp_tool_secret_selectors,
    app_secret_requests_for_arguments,
)
from core.apps.surface_policies import app_requires_full_access_runtime
from core.authorization.service import can_mount_app_visibility
from core.mcp.models import McpInvocationContext, McpInvocationPolicy, McpToolDefinition
from core.secrets.app_delivery import resolve_app_secret_payload_requests
from core.secrets.store import SecretStore
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths

APP_MCP_ENTRYPOINT_TIMEOUT_SECONDS = 30.0


def _app_mcp_invocation_policy(*, app_requires_full_access: bool) -> McpInvocationPolicy:
    return McpInvocationPolicy(
        operator_only=False,
        sandbox_agent_allowed=not app_requires_full_access,
        requires_workspace_context=True,
        requires_full_access=app_requires_full_access,
    )


def _workspace_app_tool_definitions(
    store: AppStore,
    *,
    workspace_id: str,
    workspace_store=None,
    provider_store=None,
    runtime_store=None,
    context: McpInvocationContext | None = None,
    secret_store: SecretStore | None = None,
    observability_store=None,
    app_event_bus=None,
    start_path: Path | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    definitions: list[tuple[McpToolDefinition, Any]] = []
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        if workspace_store is not None and context is not None and not can_mount_app_visibility(
            workspace_store,
            user=None,
            workspace_id=workspace_id,
            platform_roles=parsed.contract.visibility.platform_roles,
            workspace_roles=parsed.contract.visibility.workspace_roles,
            capabilities=parsed.contract.visibility.capabilities,
            platform_role=context.platform_role,
            workspace_role=context.workspace_role,
        ):
            continue
        if not parsed.contract.capabilities.mcp_tools:
            continue
        if parsed.contract.entrypoints.mcp is None:
            raise ValueError(
                f"App `{parsed.app_id}` declares MCP tools but no MCP entrypoint in its contract."
            )
        entrypoint_path = str((source_root / parsed.contract.entrypoints.mcp).resolve())
        app_requires_full_access = app_requires_full_access_runtime(parsed.contract.compatibility)
        paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
        for tool_name in parsed.contract.capabilities.mcp_tools:
            local_app_id = binding.app_id
            public_app_id = binding.public_app_id or parsed.app_id
            hosted_tool_name = f"app.{local_app_id}.{tool_name}"
            default_description = f"App MCP tool exposed by `{local_app_id}`."
            description, input_schema, output_schema = app_mcp_tool_metadata(
                source_root,
                tool_name,
                default_description=default_description,
            )
            secret_selectors = app_mcp_tool_secret_selectors(
                source_root,
                tool_name,
                declared_secret_names=parsed.contract.permissions.secrets.read,
            )
            def _handler(
                arguments: dict[str, Any],
                context: McpInvocationContext,
                *,
                _entrypoint_path: str = entrypoint_path,
                _tool_name: str = tool_name,
                _workspace_id: str = workspace_id,
                _source_root: Path = source_root,
                _app_id: str = local_app_id,
                _public_app_id: str = public_app_id,
                _data_root: str = binding.data_root,
                _workspace_root: str = str(paths.root),
                _uploaded_storage_root: str = str(paths.uploaded_storage),
                _generated_storage_root: str = str(paths.generated_storage),
                _secret_selectors: list[AppSurfaceSecretSelector] = secret_selectors,
                _declared_event_resources: list[str] = declared_data_event_resources(
                    parsed.contract.capabilities.data_events
                ),
                _parsed=parsed,
                _secret_store: SecretStore | None = secret_store,
                _workspace_store=workspace_store,
                _provider_store=provider_store,
                _runtime_store=runtime_store,
                _observability_store=observability_store,
                _app_event_bus=app_event_bus,
                _start_path: Path | None = start_path,
            ) -> dict[str, Any]:
                def _lookup_secret_resource(selector: AppSurfaceSecretSelector) -> dict[str, Any] | None:
                    return _app_secret_resource_lookup(
                        _entrypoint_path,
                        selector=selector,
                        arguments=arguments,
                        context=context,
                        tool_name=_tool_name,
                        app_id=_app_id,
                        public_app_id=_public_app_id,
                        source_root=_source_root,
                        data_root=_data_root,
                        workspace_root=_workspace_root,
                        uploaded_storage_root=_uploaded_storage_root,
                        generated_storage_root=_generated_storage_root,
                    )

                app_secret_result = resolve_app_secret_payload_requests(
                    _secret_store,
                    workspace_id=str(context.workspace_id),
                    app_id=_app_id,
                    requests=app_secret_requests_for_arguments(
                        _secret_selectors,
                        arguments,
                        resource_lookup=_lookup_secret_resource,
                    ),
                    surface=f"mcp/{_tool_name}",
                    runtime_session_id=context.runtime_session_id,
                    actor_user_id=context.user_id,
                    observability_store=_observability_store,
                    request_context={"surface": "mcp", "tool_name": _tool_name},
                )
                result = run_json_entrypoint(
                    _entrypoint_path,
                    payload={
                        "surface": "mcp",
                        "tool_name": _tool_name,
                        "workspace_id": context.workspace_id,
                        "agent_id": context.agent_id,
                        "effective_mode": context.effective_mode,
                        "platform_role": context.platform_role,
                        "user_id": context.user_id,
                        "workspace_role": context.workspace_role,
                        "runtime_session_id": context.runtime_session_id,
                        "app_id": _app_id,
                        "public_app_id": _public_app_id,
                        "workspace_root": _workspace_root,
                        "data_root": _data_root,
                        "uploaded_storage_root": _uploaded_storage_root,
                        "generated_storage_root": _generated_storage_root,
                        "app_dependencies": _app_dependencies_payload(
                            store,
                            workspace_id=str(context.workspace_id),
                            app_id=_app_id,
                            workspace_store=_workspace_store,
                            platform_role=context.platform_role,
                            workspace_role=context.workspace_role,
                            start_path=_start_path,
                        ),
                        "app_secrets": app_secret_result.secrets,
                        "app_secret_errors": app_secret_result.errors,
                        "arguments": arguments,
                    },
                    cwd=_source_root,
                    timeout_seconds=app_mcp_entrypoint_timeout_seconds(context),
                )
                publish_declared_app_events(
                    _app_event_bus,
                    result,
                    workspace_id=str(context.workspace_id),
                    app_id=_app_id,
                    declared_resources=_declared_event_resources,
                )
                if _workspace_store is not None and _provider_store is not None and _runtime_store is not None:
                    apply_app_runtime_requests(
                        SimpleNamespace(
                            app_store=store,
                            workspace_store=_workspace_store,
                            provider_store=_provider_store,
                            runtime_store=_runtime_store,
                            secret_store=_secret_store,
                            observability_store=_observability_store,
                            runtime_event_bus=None,
                            app_event_bus=_app_event_bus,
                            repository_root=_start_path,
                        ),
                        result=result,
                        workspace_id=str(context.workspace_id),
                        app_id=_app_id,
                        source_root=_source_root,
                        backend_entrypoint=_parsed.contract.entrypoints.backend,
                        data_root=_data_root,
                        parsed=_parsed,
                        start_path=_start_path or Path.cwd(),
                    )
                return result

            definitions.append(
                (
                    McpToolDefinition(
                        tool_name=hosted_tool_name,
                        description=description,
                        input_schema=input_schema,
                        output_schema=output_schema,
                        owner_kind="app",
                        owner_id=local_app_id,
                        workspace_id=workspace_id,
                        exposure_scope="workspace_enabled_app",
                        invocation_policy=_app_mcp_invocation_policy(
                            app_requires_full_access=app_requires_full_access,
                        ),
                        entrypoint_path=entrypoint_path,
                    ),
                    lambda arguments, context, _handler=_handler: _handler(arguments, context),
                )
            )
    return definitions


def _app_dependencies_payload(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    workspace_store=None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
    start_path: Path | None,
) -> dict[str, object]:
    try:
        return resolve_app_dependencies(
            store,
            workspace_id=workspace_id,
            consumer_app_id=app_id,
            workspace_store=workspace_store,
            platform_role=platform_role,
            workspace_role=workspace_role,
            start_path=start_path,
        )
    except Exception:
        return {"workspace_id": workspace_id, "consumer_app_id": app_id, "status": "blocked", "dependencies": []}


def _app_secret_resource_lookup(
    entrypoint_path: str,
    *,
    selector: AppSurfaceSecretSelector,
    arguments: dict[str, Any],
    context: McpInvocationContext,
    tool_name: str,
    app_id: str,
    public_app_id: str,
    source_root: Path,
    data_root: str,
    workspace_root: str,
    uploaded_storage_root: str,
    generated_storage_root: str,
) -> dict[str, Any] | None:
    result = run_json_entrypoint(
        entrypoint_path,
        payload={
            "surface": "secret_selector",
            "tool_name": tool_name,
            "workspace_id": context.workspace_id,
            "agent_id": context.agent_id,
            "effective_mode": context.effective_mode,
            "runtime_session_id": context.runtime_session_id,
            "app_id": app_id,
            "public_app_id": public_app_id,
            "workspace_root": workspace_root,
            "data_root": data_root,
            "uploaded_storage_root": uploaded_storage_root,
            "generated_storage_root": generated_storage_root,
            "app_secrets": {},
            "app_secret_selector": {
                "logical_names": selector.logical_names,
                "resource_type": selector.resource_type,
                "resource_id_argument": selector.resource_id_argument,
                "resource_lookup": selector.resource_lookup,
            },
            "arguments": arguments,
        },
        cwd=source_root,
        timeout_seconds=app_mcp_entrypoint_timeout_seconds(context),
    )
    return result if isinstance(result, dict) else None


def app_mcp_entrypoint_timeout_seconds(context: McpInvocationContext) -> float:
    return context.app_mcp_timeout_seconds or APP_MCP_ENTRYPOINT_TIMEOUT_SECONDS
