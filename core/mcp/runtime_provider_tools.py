"""Runtime and provider core MCP tools."""

from __future__ import annotations

from typing import Any

from core.mcp.core_tool_helpers import OPERATOR_ONLY, WORKSPACE_SAFE, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.providers.payloads import provider_payload, routing_decision_payload, sort_provider_definitions
from core.providers.provider_registry import ProviderRegistry
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import builtin_provider_registry
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
                registry=provider_registry or builtin_provider_registry(),
                secret_store=secret_store,
                request_id=str(arguments.get("request_id") or "").strip() or None,
                user_tier=str(arguments.get("user_tier") or "").strip() or None,
                app_id=str(arguments.get("app_id") or "").strip() or None,
                allow_fallback_codex=bool(arguments.get("allow_fallback_codex")),
            ),
        )
        return {"decision": routing_decision_payload(decision)}

    return [
        (
            core_mcp_tool(
                tool_name="core.runtime.status",
                description="Inspect runtime session status for the active workspace.",
                owner_id="runtime",
                invocation_policy=WORKSPACE_SAFE,
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
