"""App-contributed CLI command mounting."""

from __future__ import annotations

import json
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
    app_cli_command_metadata,
    app_cli_command_secret_selectors,
    app_secret_requests_for_arguments,
)
from core.apps.surface_policies import app_requires_full_access_runtime
from core.authorization.service import can_mount_app_visibility
from core.cli.models import CliCommandDefinition, CliInvocationContext, CliInvocationPolicy
from core.secrets.app_delivery import resolve_app_secret_payload_requests
from core.secrets.store import SecretStore
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths


def _app_command_invocation_policy(
    source_root: Path,
    command_name: str,
    *,
    app_requires_full_access: bool,
) -> CliInvocationPolicy:
    default_sandbox_agent_allowed = not app_requires_full_access
    policy_path = source_root / "cli" / "command_policies.json"
    if policy_path.is_file():
        payload = _load_cli_policy_payload(policy_path)
        command_policy = payload.get("commands", {}).get(command_name)
        if command_policy is not None:
            if not isinstance(command_policy, dict):
                raise ValueError(
                    f"App CLI command policy `{policy_path}` command `{command_name}` must be an object."
                )
            required_platform_role = command_policy.get("required_platform_role")
            if required_platform_role not in {None, "admin", "member"}:
                raise ValueError(
                    f"App CLI command policy `{policy_path}` command `{command_name}` has invalid platform role."
                )
            if command_policy.get("operator_only") is True:
                raise ValueError(
                    f"App CLI command policy `{policy_path}` command `{command_name}` cannot set `operator_only`."
                )
            sandbox_agent_allowed = _policy_bool(
                command_policy,
                "sandbox_agent_allowed",
                default=default_sandbox_agent_allowed,
            )
            requires_full_access = _policy_bool(
                command_policy,
                "requires_full_access",
                default=app_requires_full_access,
            )
            if app_requires_full_access:
                sandbox_agent_allowed = False
                requires_full_access = True
            return CliInvocationPolicy(
                operator_only=_policy_bool(command_policy, "operator_only", default=False),
                required_platform_role=required_platform_role,
                sandbox_agent_allowed=sandbox_agent_allowed,
                requires_workspace_context=_policy_bool(
                    command_policy,
                    "requires_workspace_context",
                    default=True,
                ),
                requires_full_access=requires_full_access,
            )
    return CliInvocationPolicy(
        operator_only=False,
        required_platform_role=None,
        sandbox_agent_allowed=default_sandbox_agent_allowed,
        requires_workspace_context=True,
        requires_full_access=app_requires_full_access,
    )


def _load_cli_policy_payload(policy_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"App CLI command policy `{policy_path}` is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise ValueError(f"App CLI command policy `{policy_path}` must be a JSON object.")
    commands = payload.get("commands", {})
    if not isinstance(commands, dict):
        raise ValueError(f"App CLI command policy `{policy_path}` field `commands` must be an object.")
    unexpected = set(payload) - {"commands"}
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ValueError(f"App CLI command policy `{policy_path}` has unsupported field(s): {names}.")
    return payload


def _policy_bool(payload: dict[str, Any], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"App CLI command policy field `{key}` must be a boolean.")
    return value


def _workspace_app_command_specs(
    store: AppStore,
    *,
    workspace_id: str,
    workspace_store=None,
    provider_store=None,
    runtime_store=None,
    context: CliInvocationContext | None = None,
    secret_store: SecretStore | None = None,
    observability_store=None,
    app_event_bus=None,
    start_path: Path | None = None,
) -> list[tuple[CliCommandDefinition, Any]]:
    specs: list[tuple[CliCommandDefinition, Any]] = []
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
        if not parsed.contract.capabilities.cli_commands:
            continue
        if parsed.contract.entrypoints.cli is None:
            raise ValueError(
                f"App `{parsed.app_id}` declares CLI commands but no CLI entrypoint in its contract."
            )
        entrypoint_path = str((source_root / parsed.contract.entrypoints.cli).resolve())
        app_requires_full_access = app_requires_full_access_runtime(parsed.contract.compatibility)
        paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
        for command_name in parsed.contract.capabilities.cli_commands:
            local_app_id = binding.app_id
            public_app_id = binding.public_app_id or parsed.app_id
            command_id = f"app.{local_app_id}.{command_name}"
            default_description = f"Workspace app CLI command `{command_name}` for `{local_app_id}`."
            description, argument_schema = app_cli_command_metadata(
                source_root,
                command_name,
                default_description=default_description,
            )
            secret_selectors = app_cli_command_secret_selectors(
                source_root,
                command_name,
                declared_secret_names=parsed.contract.permissions.secrets.read,
            )

            def _handler(
                arguments: dict[str, Any],
                context: CliInvocationContext,
                *,
                _command_id: str = command_id,
                _app_id: str = local_app_id,
                _public_app_id: str = public_app_id,
                _entrypoint_path: str = entrypoint_path,
                _source_root: Path = source_root,
                _data_root: str = binding.data_root,
                _workspace_root: str = str(paths.root),
                _uploaded_storage_root: str = str(paths.uploaded_storage),
                _generated_storage_root: str = str(paths.generated_storage),
                _command_name: str = command_name,
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
                    surface=f"cli/{_command_name}",
                    runtime_session_id=context.runtime_session_id,
                    actor_user_id=context.user_id,
                    observability_store=_observability_store,
                    request_context={"surface": "cli", "command_id": _command_id},
                )
                result = run_json_entrypoint(
                    _entrypoint_path,
                    payload={
                        "surface": "cli",
                        "command_id": _command_id,
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
                )
                publish_declared_app_events(
                    _app_event_bus,
                    result,
                    workspace_id=context.workspace_id,
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

            specs.append(
                (
                    CliCommandDefinition(
                        command_id=command_id,
                        path_segments=["app", local_app_id, command_name],
                        description=description,
                        argument_schema=argument_schema,
                        owner_kind="app",
                        owner_id=local_app_id,
                        workspace_id=workspace_id,
                        exposure_scope="workspace_enabled_app",
                        invocation_policy=_app_command_invocation_policy(
                            source_root,
                            command_name,
                            app_requires_full_access=app_requires_full_access,
                        ),
                        entrypoint_path=entrypoint_path,
                    ),
                    _handler,
                )
            )
    return specs


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
    context: CliInvocationContext,
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
    )
    return result if isinstance(result, dict) else None
