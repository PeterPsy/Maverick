"""Secret-management core MCP tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.api.secret_api_payloads import grant_payload
from core.api.secret_grant_admin import (
    create_secret_grant_from_payload,
    list_grant_payloads,
    list_secret_audit_payloads,
    list_secret_grant_recommendations,
    list_secret_grant_targets,
    revoke_workspace_secret_grant,
)
from core.apps.store import AppStore
from core.mcp.core_tool_helpers import OPERATOR_ONLY, WORKSPACE_SAFE, core_mcp_tool, record_mcp_audit
from core.mcp.models import McpInvocationContext, McpToolDefinition
from core.secrets.audit import record_cascaded_grant_revocation_audit
from core.secrets.service import (
    create_platform_secret,
    disable_platform_secret_with_revocations,
    revoke_platform_secret_with_revocations,
    rotate_platform_secret,
    update_platform_secret_metadata,
)
from core.secrets.models import SecretRecord
from core.secrets.store import SecretStore


def secret_tool_specs(
    *,
    app_store: AppStore | None = None,
    secret_store: SecretStore | None = None,
    observability_store=None,
    start_path: Path | None = None,
) -> list[tuple[McpToolDefinition, Any]]:
    """Build platform secret MCP tool specs."""
    def _workspace_id(arguments: dict[str, Any], context: McpInvocationContext) -> str:
        return str(arguments.get("workspace_id") or context.workspace_id or "").strip()

    def _admin_state():
        if app_store is None or secret_store is None or start_path is None:
            return None
        return SimpleNamespace(
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            repository_root=start_path,
        )

    def _secrets_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"items": []}
        return {"items": [_secret_metadata_payload(item) for item in secret_store.list_secrets()]}

    def _secret_grants_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        state = _admin_state()
        workspace_id = _workspace_id(arguments, context)
        if state is None or not workspace_id:
            return {"items": []}
        return {"items": list_grant_payloads(state, workspace_id=workspace_id)}

    def _secret_grant_create_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        state = _admin_state()
        workspace_id = _workspace_id(arguments, context)
        if state is None:
            return {"created": False}
        grant, secret = create_secret_grant_from_payload(
            state,
            workspace_id=workspace_id,
            payload=arguments,
            created_by_user_id=context.user_id,
        )
        record_mcp_audit(
            observability_store,
            event_type="core.secrets.grant.create",
            workspace_id=workspace_id,
            runtime_session_id=context.runtime_session_id,
            payload={
                "grant_id": grant.grant_id,
                "app_id": grant.app_id,
                "secret_id": secret.secret_id,
                "secret_ref": grant.secret_ref,
            },
        )
        return {"created": True, "grant": grant_payload(grant, state=state)}

    def _secret_grant_revoke_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        state = _admin_state()
        workspace_id = _workspace_id(arguments, context)
        if state is None:
            return {"revoked": False}
        grant = revoke_workspace_secret_grant(state, workspace_id=workspace_id, grant_id=str(arguments["grant_id"]))
        record_mcp_audit(
            observability_store,
            event_type="core.secrets.grant.revoke",
            workspace_id=workspace_id,
            runtime_session_id=context.runtime_session_id,
            payload={"grant_id": grant.grant_id, "app_id": grant.app_id},
        )
        return {"revoked": True, "grant": grant_payload(grant, state=state)}

    def _secret_grant_targets_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        state = _admin_state()
        workspace_id = _workspace_id(arguments, context)
        if state is None or not workspace_id:
            return {"items": [], "needs": []}
        return list_secret_grant_targets(state, workspace_id=workspace_id)

    def _secret_grant_targets_recommend_handler(
        arguments: dict[str, Any],
        context: McpInvocationContext,
    ) -> dict[str, Any]:
        state = _admin_state()
        workspace_id = _workspace_id(arguments, context)
        if state is None or not workspace_id:
            return {"items": []}
        return {"items": list_secret_grant_recommendations(state, workspace_id=workspace_id)}

    def _secret_audit_list_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        state = _admin_state()
        workspace_id = _workspace_id(arguments, context)
        if state is None or not workspace_id:
            return {"items": []}
        return {"items": list_secret_audit_payloads(state, workspace_id=workspace_id)}

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
        record_mcp_audit(
            observability_store,
            event_type="core.secrets.create",
            payload={"secret_id": secret.secret_id, "alias": secret.alias},
        )
        return {
            "created": True,
            "secret": {
                "secret_id": secret.secret_id,
                "alias": secret.alias,
                "label": secret.label,
                "status": secret.status,
            },
        }

    def _secret_rotate_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"rotated": False}
        secret = rotate_platform_secret(
            secret_store,
            secret_id=str(arguments["secret_id"]),
            raw_value=str(arguments["raw_value"]),
        )
        record_mcp_audit(observability_store, event_type="core.secrets.rotate", payload={"secret_id": secret.secret_id})
        return {"rotated": True, "secret_id": secret.secret_id, "status": secret.status}

    def _secret_update_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"updated": False}
        current = secret_store.get_secret(str(arguments["secret_id"]))
        secret = update_platform_secret_metadata(
            secret_store,
            secret_id=current.secret_id,
            label=str(arguments.get("label", current.label)),
            alias=_optional_metadata_value(arguments, "alias", current.alias),
            description=_optional_metadata_value(arguments, "description", current.description),
            kind=str(arguments.get("kind", current.kind)),
        )
        record_mcp_audit(
            observability_store,
            event_type="core.secrets.update",
            payload={"secret_id": secret.secret_id, "alias": secret.alias},
        )
        return {"updated": True, "secret": _secret_metadata_payload(secret)}

    def _secret_disable_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"disabled": False}
        result = disable_platform_secret_with_revocations(secret_store, secret_id=str(arguments["secret_id"]))
        secret = result.secret
        record_mcp_audit(
            observability_store,
            event_type="core.secrets.disable",
            payload={"secret_id": secret.secret_id, "revoked_grant_count": len(result.revoked_grants)},
        )
        record_cascaded_grant_revocation_audit(
            observability_store,
            secret_id=secret.secret_id,
            grants=result.revoked_grants,
            actor_user_id=context.user_id,
            actor_agent_id=context.agent_id,
            runtime_session_id=context.runtime_session_id,
            source_workspace_id=context.workspace_id,
        )
        return {
            "disabled": True,
            "secret_id": secret.secret_id,
            "status": secret.status,
            "revoked_grant_count": len(result.revoked_grants),
        }

    def _secret_revoke_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"revoked": False}
        result = revoke_platform_secret_with_revocations(secret_store, secret_id=str(arguments["secret_id"]))
        secret = result.secret
        record_mcp_audit(
            observability_store,
            event_type="core.secrets.revoke",
            payload={"secret_id": secret.secret_id, "revoked_grant_count": len(result.revoked_grants)},
        )
        record_cascaded_grant_revocation_audit(
            observability_store,
            secret_id=secret.secret_id,
            grants=result.revoked_grants,
            actor_user_id=context.user_id,
            actor_agent_id=context.agent_id,
            runtime_session_id=context.runtime_session_id,
            source_workspace_id=context.workspace_id,
        )
        return {
            "revoked": True,
            "secret_id": secret.secret_id,
            "status": secret.status,
            "revoked_grant_count": len(result.revoked_grants),
        }

    grant_create_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace_id": {"type": "string", "minLength": 1},
            "app_id": {"type": "string", "minLength": 1},
            "logical_name": {"type": "string", "minLength": 1},
            "secret_ref": {"type": "string", "minLength": 1},
            "secret_id": {"type": "string", "minLength": 1},
            "alias": {"type": "string", "minLength": 1},
            "actions": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
            "target_patterns": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "expires_at": {"type": "string", "minLength": 1},
            "reason": {"type": "string"},
            "resource_type": {"type": "string", "minLength": 1},
            "resource_id": {"type": "string", "minLength": 1},
        },
        "required": ["app_id", "logical_name", "actions"],
        "oneOf": [
            {"required": ["secret_ref"]},
            {"required": ["secret_id"]},
            {"required": ["alias"]},
        ],
    }
    workspace_list_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"workspace_id": {"type": "string", "minLength": 1}},
    }
    secret_update_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "secret_id": {"type": "string", "minLength": 1},
            "label": {"type": "string", "minLength": 1},
            "alias": {"type": ["string", "null"], "minLength": 1},
            "description": {"type": ["string", "null"]},
            "kind": {"type": "string", "enum": ["generic", "password", "api_key", "oauth_token", "private_key"]},
        },
        "required": ["secret_id"],
        "anyOf": [
            {"required": ["label"]},
            {"required": ["alias"]},
            {"required": ["description"]},
            {"required": ["kind"]},
        ],
    }
    tool_specs = [
        (
            "core.secrets.list",
            "Inspect platform secret metadata without raw values.",
            _secrets_list_handler,
            OPERATOR_ONLY,
            {"type": "object", "additionalProperties": False},
        ),
        (
            "core.secret_grants.list",
            "Inspect workspace secret grant metadata without raw values.",
            _secret_grants_list_handler,
            WORKSPACE_SAFE,
            workspace_list_schema,
        ),
        (
            "core.secret_grants.create",
            "Create one app secret grant after core validation.",
            _secret_grant_create_handler,
            OPERATOR_ONLY,
            grant_create_schema,
        ),
        (
            "core.secret_grants.revoke",
            "Revoke one app secret grant.",
            _secret_grant_revoke_handler,
            OPERATOR_ONLY,
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "workspace_id": {"type": "string", "minLength": 1},
                    "grant_id": {"type": "string", "minLength": 1},
                },
                "required": ["grant_id"],
            },
        ),
        (
            "core.secret_grant_targets.list",
            "Inspect redaction-safe app secret grant target metadata.",
            _secret_grant_targets_list_handler,
            WORKSPACE_SAFE,
            workspace_list_schema,
        ),
        (
            "core.secret_grant_targets.recommend",
            "List recommended secret grant specs derived from app consumers.",
            _secret_grant_targets_recommend_handler,
            WORKSPACE_SAFE,
            workspace_list_schema,
        ),
        (
            "core.secret_audit.list",
            "Inspect redaction-safe Core Secrets audit records.",
            _secret_audit_list_handler,
            WORKSPACE_SAFE,
            workspace_list_schema,
        ),
        (
            "core.secrets.create",
            "Create one platform secret without exposing the raw value in the result.",
            _secret_create_handler,
            OPERATOR_ONLY,
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string", "minLength": 1},
                    "raw_value": {"type": "string"},
                    "alias": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                },
                "required": ["label", "raw_value"],
            },
        ),
        (
            "core.secrets.rotate",
            "Rotate one platform secret without exposing the raw value.",
            _secret_rotate_handler,
            OPERATOR_ONLY,
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "secret_id": {"type": "string", "minLength": 1},
                    "raw_value": {"type": "string"},
                },
                "required": ["secret_id", "raw_value"],
            },
        ),
        (
            "core.secrets.update",
            "Update redaction-safe platform secret metadata without reading or changing the raw value.",
            _secret_update_handler,
            OPERATOR_ONLY,
            secret_update_schema,
        ),
        (
            "core.secrets.disable",
            "Disable one platform secret.",
            _secret_disable_handler,
            OPERATOR_ONLY,
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"secret_id": {"type": "string", "minLength": 1}},
                "required": ["secret_id"],
            },
        ),
        (
            "core.secrets.revoke",
            "Revoke one platform secret and remove its raw value.",
            _secret_revoke_handler,
            OPERATOR_ONLY,
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"secret_id": {"type": "string", "minLength": 1}},
                "required": ["secret_id"],
            },
        ),
    ]
    return [
        (
            core_mcp_tool(
                tool_name=tool_name,
                description=description,
                owner_id="secrets",
                invocation_policy=invocation_policy,
                input_schema=input_schema,
            ),
            handler,
        )
        for tool_name, description, handler, invocation_policy, input_schema in tool_specs
    ]


def _optional_metadata_value(arguments: dict[str, Any], key: str, current: str | None) -> str | None:
    if key not in arguments:
        return current
    value = arguments[key]
    return None if value is None else str(value)


def _secret_metadata_payload(secret: SecretRecord) -> dict[str, Any]:
    return {
        "secret_id": secret.secret_id,
        "alias": secret.alias,
        "label": secret.label,
        "description": secret.description,
        "kind": secret.kind,
        "status": secret.status,
    }
