"""Runtime and provider core MCP tools."""

from __future__ import annotations

from typing import Any

from core.mcp.core_tool_helpers import OPERATOR_ONLY, WORKSPACE_SAFE, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.providers.payloads import (
    hosted_provider_selection_payload,
    provider_payload,
    routing_decision_payload,
    sort_provider_definitions,
)
from core.providers.provider_registry import ProviderRegistry
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import activate_hosted_model_provider, effective_provider_registry, is_retired_provider_definition
from core.providers.store import ProviderStore
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.store import RuntimeStore
from core.secrets.store import SecretStore


def runtime_provider_tool_specs(
    *,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    secret_store: SecretStore | None = None,
    observability_store=None,
) -> list[tuple[McpToolDefinition, Any]]:
    """Build runtime and provider MCP tool specs."""
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
                    "runtime_mode": item.runtime_mode,
                }
                for item in runtime_store.list_sessions(workspace_id)
                if runtime_session_allows_user_thread(item)
            ],
        }

    def _providers_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        definitions = _provider_definitions(provider_store, provider_registry)
        if not definitions:
            return {"items": []}
        return {
            "items": [provider_payload(item) for item in definitions]
        }

    def _providers_route_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"error": "provider_store_unavailable"}
        workspace_id = str(arguments.get("workspace_id") or context.workspace_id or "").strip()
        if not workspace_id:
            return {"error": "workspace_id_required"}
        decision = select_provider_for_profile(
            str(arguments.get("profile") or "fast_model"),
            ProviderRoutingContext(
                workspace_id=workspace_id,
                provider_store=provider_store,
                registry=effective_provider_registry(provider_store, registry=provider_registry),
                secret_store=secret_store,
                request_id=str(arguments.get("request_id") or "").strip() or None,
                user_tier=str(arguments.get("user_tier") or "").strip() or None,
                app_id=str(arguments.get("app_id") or "").strip() or None,
                allow_fallback_codex=bool(arguments.get("allow_fallback_codex")),
            ),
        )
        return {"decision": routing_decision_payload(decision)}

    def _providers_hosted_activate_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"error": "provider_store_unavailable"}
        if secret_store is None:
            return {"error": "secret_store_unavailable"}
        workspace_id = str(arguments.get("workspace_id") or context.workspace_id or "").strip()
        provider_id = str(arguments.get("provider_id") or "").strip()
        secret_ref = str(arguments.get("secret_ref") or "").strip()
        if not workspace_id:
            return {"error": "workspace_id_required"}
        if not provider_id:
            return {"error": "provider_id_required"}
        if not secret_ref:
            return {"error": "secret_ref_required"}
        try:
            activation = activate_hosted_model_provider(
                provider_store,
                secret_store=secret_store,
                workspace_id=workspace_id,
                provider_id=provider_id,
                secret_ref=secret_ref,
                label=str(arguments.get("label") or "").strip() or None,
                observability_store=observability_store,
            )
        except Exception as error:
            return {
                "error": "hosted_provider_activation_failed",
                "error_type": type(error).__name__,
            }
        return {
            "workspace_id": workspace_id,
            "provider": provider_payload(activation.definition),
            "credential_binding": _provider_credential_binding_payload(activation.credential_binding),
            "hosted_selection": hosted_provider_selection_payload(activation.hosted_selection),
            "preflight": routing_decision_payload(activation.routing_decision),
        }

    return [
        (
            core_mcp_tool(
                tool_name="core.runtime.status",
                description="Inspect runtime session status for the active workspace.",
                owner_id="runtime",
                invocation_policy=OPERATOR_ONLY,
            ),
            _runtime_status_handler,
        ),
        (
            core_mcp_tool(
                tool_name="core.providers.list",
                description="Inspect configured provider definitions and availability.",
                owner_id="providers",
                invocation_policy=OPERATOR_ONLY,
                input_schema={},
            ),
            _providers_list_handler,
        ),
        (
            core_mcp_tool(
                tool_name="core.providers.route",
                description="Simulate a read-only provider routing decision.",
                owner_id="providers",
                invocation_policy=WORKSPACE_SAFE,
                input_schema={
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
        (
            core_mcp_tool(
                tool_name="core.providers.hosted.activate",
                description="Operator activation for a hosted text model provider.",
                owner_id="providers",
                invocation_policy=OPERATOR_ONLY,
                input_schema={
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "provider_id": {"type": "string"},
                        "secret_ref": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["provider_id", "secret_ref"],
                    "additionalProperties": False,
                },
            ),
            _providers_hosted_activate_handler,
        ),
    ]


def _provider_credential_binding_payload(binding) -> dict[str, object] | None:
    if binding is None:
        return None
    return {
        "binding_id": binding.binding_id,
        "provider_id": binding.provider_id,
        "workspace_id": binding.workspace_id,
        "label": binding.label,
        "status": binding.status,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def _provider_definitions(
    provider_store: ProviderStore | None,
    provider_registry: ProviderRegistry | None,
) -> list:
    if provider_store is not None:
        registry = effective_provider_registry(provider_store, registry=provider_registry)
        return sort_provider_definitions([
            definition
            for definition in registry.list_provider_definitions()
            if not is_retired_provider_definition(definition)
        ])
    if provider_registry is not None:
        return sort_provider_definitions([
            definition
            for definition in provider_registry.list_provider_definitions()
            if not is_retired_provider_definition(definition)
        ])
    return []
