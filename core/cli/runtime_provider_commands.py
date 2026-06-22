"""Runtime and provider core CLI commands."""

from __future__ import annotations

from typing import Any

from core.cli.core_command_helpers import WORKSPACE_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.providers.payloads import provider_payload, routing_decision_payload, sort_provider_definitions
from core.providers.provider_registry import ProviderRegistry
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import builtin_provider_registry
from core.providers.store import ProviderStore
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.store import RuntimeStore
from core.secrets.store import SecretStore


def runtime_provider_command_specs(
    *,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    secret_store: SecretStore | None = None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build runtime and provider command specs."""
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
                if runtime_session_allows_user_thread(item)
            ],
        }

    def _providers_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        definitions = _provider_definitions(provider_store, provider_registry)
        if not definitions:
            return {"providers": []}
        return {
            "command_id": "core.providers.list",
            "providers": [provider_payload(item) for item in definitions],
        }

    def _providers_route_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"command_id": "core.providers.route", "error": "provider_store_unavailable"}
        workspace_id = str(arguments.get("workspace_id") or context.workspace_id or "").strip()
        if not workspace_id:
            return {"command_id": "core.providers.route", "error": "workspace_id_required"}
        decision = select_provider_for_profile(
            str(arguments.get("profile") or "fast_model"),
            ProviderRoutingContext(
                workspace_id=workspace_id,
                provider_store=provider_store,
                registry=provider_registry or builtin_provider_registry(),
                secret_store=secret_store,
                request_id=str(arguments.get("request_id") or "").strip() or None,
                user_tier=str(arguments.get("user_tier") or "").strip() or None,
                app_id=str(arguments.get("app_id") or "").strip() or None,
                allow_fallback_codex=bool(arguments.get("allow_fallback_codex")),
            ),
        )
        return {"command_id": "core.providers.route", "decision": routing_decision_payload(decision)}

    return [
        (
            core_cli_command(
                command_id="core.runtime.status",
                path_segments=["core", "runtime", "status"],
                description="Inspect runtime status for the active workspace.",
                owner_id="runtime",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _runtime_status_handler,
        ),
        (
            core_cli_command(
                command_id="core.providers.list",
                path_segments=["core", "providers", "list"],
                description="Inspect configured provider definitions.",
                owner_id="providers",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _providers_list_handler,
        ),
        (
            core_cli_command(
                command_id="core.providers.route",
                path_segments=["core", "providers", "route"],
                description="Simulate a read-only provider routing decision.",
                owner_id="providers",
                invocation_policy=WORKSPACE_SAFE,
                argument_schema={
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "profile": {"type": "string"},
                        "request_id": {"type": "string"},
                        "user_tier": {"type": "string"},
                        "app_id": {"type": "string"},
                        "allow_fallback_codex": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            ),
            _providers_route_handler,
        ),
    ]


def _provider_definitions(
    provider_store: ProviderStore | None,
    provider_registry: ProviderRegistry | None,
) -> list:
    if provider_store is not None:
        return sort_provider_definitions(provider_store.list_provider_definitions())
    if provider_registry is not None:
        return sort_provider_definitions(provider_registry.list_provider_definitions())
    return []
