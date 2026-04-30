"""Secret-management core MCP tools."""

from __future__ import annotations

from typing import Any

from core.mcp.core_tool_helpers import OPERATOR_ONLY, core_mcp_tool, record_mcp_audit
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.secrets.service import create_platform_secret, disable_platform_secret, revoke_platform_secret, rotate_platform_secret
from core.secrets.store import SecretStore


def secret_tool_specs(
    *,
    secret_store: SecretStore | None = None,
    observability_store=None,
) -> list[tuple[McpToolDefinition, Any]]:
    """Build platform secret MCP tool specs."""
    def _secrets_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"items": []}
        return {
            "items": [
                {"secret_id": item.secret_id, "alias": item.alias, "label": item.label, "status": item.status}
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
        record_mcp_audit(observability_store, event_type="core.secrets.create", payload={"secret_id": secret.secret_id, "alias": secret.alias})
        return {"created": True, "secret": {"secret_id": secret.secret_id, "alias": secret.alias, "label": secret.label, "status": secret.status}}

    def _secret_rotate_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"rotated": False}
        secret = rotate_platform_secret(secret_store, secret_id=str(arguments["secret_id"]), raw_value=str(arguments["raw_value"]))
        record_mcp_audit(observability_store, event_type="core.secrets.rotate", payload={"secret_id": secret.secret_id})
        return {"rotated": True, "secret_id": secret.secret_id, "status": secret.status}

    def _secret_disable_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"disabled": False}
        secret = disable_platform_secret(secret_store, secret_id=str(arguments["secret_id"]))
        record_mcp_audit(observability_store, event_type="core.secrets.disable", payload={"secret_id": secret.secret_id})
        return {"disabled": True, "secret_id": secret.secret_id, "status": secret.status}

    def _secret_revoke_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"revoked": False}
        secret = revoke_platform_secret(secret_store, secret_id=str(arguments["secret_id"]))
        record_mcp_audit(observability_store, event_type="core.secrets.revoke", payload={"secret_id": secret.secret_id})
        return {"revoked": True, "secret_id": secret.secret_id, "status": secret.status}

    tool_specs = [
        ("core.secrets.list", "Inspect platform secret metadata without raw values.", _secrets_list_handler, {}),
        ("core.secrets.create", "Create one platform secret without exposing the raw value in the result.", _secret_create_handler, {"type": "object"}),
        ("core.secrets.rotate", "Rotate one platform secret without exposing the raw value.", _secret_rotate_handler, {"type": "object"}),
        ("core.secrets.disable", "Disable one platform secret.", _secret_disable_handler, {"type": "object"}),
        ("core.secrets.revoke", "Revoke one platform secret and remove its raw value.", _secret_revoke_handler, {"type": "object"}),
    ]
    return [
        (
            core_mcp_tool(
                tool_name=tool_name,
                description=description,
                owner_id="secrets",
                invocation_policy=OPERATOR_ONLY,
                input_schema=input_schema,
            ),
            handler,
        )
        for tool_name, description, handler, input_schema in tool_specs
    ]
