"""Schemas, context projection, and classification for tool discovery."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

from core.cli.models import CliInvocationContext
from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
)
from core.mcp.models import McpInvocationContext
from core.runtime.tool_catalog import (
    RuntimeCoreCapabilitySurface,
    RuntimeExternalToolSurface,
)
from core.runtime.tool_errors import RuntimeToolError


MAX_DISCOVERY_RESULTS = 50
CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT = "tool-schema-catalog"


def discovery_surface(name, description, schema, effect_class, handler):
    return RuntimeCoreCapabilitySurface(
        definition=RuntimeExternalToolSurface(
            handle=f"core-capability:{name}",
            description=description,
            input_schema=schema,
            output_schema=None,
            effect_class=effect_class,
            safe_to_retry=effect_class == "read",
            owner_kind="core",
            schema_public=True,
            certified_tcb_component=CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT,
        ),
        handler=handler,
        allowed_execution_modes=("sandbox", "full-access"),
    )


def cli_context(context, *, idempotency_key=None):
    return CliInvocationContext(
        caller_kind=(
            "full_access_agent"
            if context.execution_mode == "full-access"
            else "sandbox_agent"
        ),
        workspace_id=context.workspace_id,
        agent_id=context.agent_id,
        effective_mode=context.execution_mode,
        platform_role=context.platform_role,
        user_id=context.actor_id,
        workspace_role=context.workspace_role,
        runtime_session_id=context.session_id,
        idempotency_key=idempotency_key,
    )


def mcp_context(context, *, idempotency_key=None):
    return McpInvocationContext(
        caller_kind=(
            "full_access_agent"
            if context.execution_mode == "full-access"
            else "sandbox_agent"
        ),
        workspace_id=context.workspace_id,
        agent_id=context.agent_id,
        effective_mode=context.execution_mode,
        platform_role=context.platform_role,
        user_id=context.actor_id,
        workspace_role=context.workspace_role,
        runtime_session_id=context.session_id,
        idempotency_key=idempotency_key,
    )


def discovery_classification(payload, *, source_ref, revision, public):
    payload_digest = digest(payload)
    if not public:
        return fail_closed_classification(
            provenance="tool_result",
            source_ref=source_ref,
            source_revision=revision,
            source_digest=payload_digest,
            resource_identity=f"{source_ref}:{revision}",
        )
    return CanonicalSourceClassification(
        data_class="public",
        provenance="tool_result",
        trust_level="trusted_platform",
        source_ref=source_ref,
        source_revision=revision,
        source_digest=payload_digest,
        resource_identity=f"{source_ref}:{revision}",
        classification_revision=1,
    )


def registry_revision(cli_registry, mcp_registry) -> str:
    return digest(
        {
            "cli": [asdict(item) for item in cli_registry.list_commands()],
            "mcp": [asdict(item) for item in mcp_registry.list_tools()],
        }
    )


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def required_string(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise RuntimeToolError("tool_arguments_invalid")
    return value


def list_schema():
    return {
        "type": "object",
        "properties": {
            "cursor": {"type": "integer", "minimum": 0},
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_DISCOVERY_RESULTS,
            },
        },
        "additionalProperties": False,
    }


def call_schema(target_field):
    return {
        "type": "object",
        "properties": {
            target_field: {"type": "string", "minLength": 1, "maxLength": 512},
            "invocation_token": {
                "type": "string",
                "minLength": 32,
                "maxLength": 2048,
            },
            "arguments": {"type": "object"},
        },
        "required": [target_field, "invocation_token", "arguments"],
        "additionalProperties": False,
    }
