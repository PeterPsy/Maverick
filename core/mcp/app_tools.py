"""App-contributed MCP tool mounting."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from typing import Any

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.apps.runtime_requests import apply_app_runtime_requests
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.authorization.service import can_mount_app_visibility
from core.mcp.models import McpInvocationContext, McpInvocationPolicy, McpToolDefinition
from core.secrets.service import resolve_app_secret
from core.secrets.store import SecretStore
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths

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
                _allowed_secret_names: list[str] = parsed.contract.permissions.secrets.read,
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
                result = run_json_entrypoint(
                    _entrypoint_path,
                    payload={
                        "surface": "mcp",
                        "tool_name": _tool_name,
                        "workspace_id": context.workspace_id,
                        "agent_id": context.agent_id,
                        "effective_mode": context.effective_mode,
                        "runtime_session_id": context.runtime_session_id,
                        "app_id": _app_id,
                        "workspace_root": _workspace_root,
                        "data_root": _data_root,
                        "uploaded_storage_root": _uploaded_storage_root,
                        "generated_storage_root": _generated_storage_root,
                        "app_secrets": _resolve_app_secret_payload(
                            _secret_store,
                            workspace_id=str(context.workspace_id),
                            app_id=_app_id,
                            allowed_logical_names=_allowed_secret_names,
                        ),
                        "arguments": arguments,
                    },
                    cwd=_source_root,
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
                        actor_user_id=context.user_id,
                    )
                return result

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


def _resolve_app_secret_payload(
    secret_store: SecretStore | None,
    *,
    workspace_id: str,
    app_id: str,
    allowed_logical_names: list[str] | None = None,
) -> dict[str, str]:
    if secret_store is None:
        return {}
    secrets: dict[str, str] = {}
    allowed = set(allowed_logical_names or [])
    for binding in secret_store.list_secret_bindings(workspace_id=workspace_id, app_id=app_id, scope="app"):
        if binding.status != "active":
            continue
        if binding.logical_name not in allowed:
            continue
        lease = resolve_app_secret(secret_store, workspace_id=workspace_id, app_id=app_id, logical_name=binding.logical_name)
        secrets[binding.logical_name] = lease.value
    return secrets
