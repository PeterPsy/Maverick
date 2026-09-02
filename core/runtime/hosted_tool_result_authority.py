"""Exact-byte and certified-definition authority for hosted tool results."""

from __future__ import annotations

import json

from core.egress.classification import content_sha256, validated_classification
from core.runtime.content_data_classification import classify_runtime_content
from core.runtime.public_content_authority import (
    runtime_public_content_authority_is_active,
)
from core.runtime.public_content_classification import (
    classification_from_runtime_public_content_authority,
)
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolSurfaceResult
from core.runtime.hosted_tool_result_projections import (
    definition_has_certified_result_projection,
)


HOSTED_TOOL_RESULT_ADMISSION_REVISION = 8
_CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT = "tool-schema-catalog"


def _content_derived_surface(
    source_handle: str,
    payload: dict[str, object],
    context: RuntimeToolActorContext,
    *,
    core_session_token_fields: bool = False,
    declared_public: bool = False,
    public_content_authority=None,
) -> RuntimeToolSurfaceResult:
    classification_payload = (
        _without_core_session_tokens(payload)
        if core_session_token_fields
        else payload
    )
    detected = classify_runtime_content(
        classification_payload,
        content_type=(
            "text/plain"
            if core_session_token_fields
            else "application/json"
        ),
    )
    digest = _payload_digest(payload)
    authority = classification_from_runtime_public_content_authority(
        public_content_authority,
        workspace_id=context.workspace_id,
        provenance="tool_result",
        trust_level="untrusted_tool_output",
        source_ref=f"core-hosted-tool-result:{source_handle}",
        source_revision=digest,
        source_digest=digest,
        resource_identity=(
            "core-hosted-tool-result:"
            f"{context.workspace_id}:{context.session_id}:"
            f"{source_handle}:{digest}"
        ),
        detected_data_class=detected,
    )
    data_class = detected
    classification_revision = HOSTED_TOOL_RESULT_ADMISSION_REVISION
    authority_ref = ""
    classification_authority = None
    if authority.classification_revision is not None:
        data_class = authority.data_class
        classification_revision = authority.classification_revision
        authority_ref = (
            f":authority:{public_content_authority.classification_id}:"
            f"{public_content_authority.revision}:"
            f"{public_content_authority.resource_digest}"
        )
        classification_authority = authority
    elif detected == "unclassified" and declared_public:
        data_class = "public"
        authority_ref = ":core-result-contract"
    return _admitted_surface(
        source_handle,
        payload,
        context,
        data_class=data_class,
        trust_level="untrusted_tool_output",
        classification_revision=classification_revision,
        authority_ref=authority_ref,
        classification_authority=classification_authority,
    )


def _without_core_session_tokens(payload: dict[str, object]) -> dict[str, object]:
    """Exclude only Core-minted same-session invocation tokens from scanning."""
    projected = dict(payload)
    for collection in ("commands", "tools"):
        raw_items = projected.get(collection)
        if not isinstance(raw_items, list):
            continue
        items: list[object] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                items.append(raw_item)
                continue
            item = dict(raw_item)
            if "invocation_token" in item:
                item["invocation_token"] = "core-session-invocation-token"
            items.append(item)
        projected[collection] = items
    return projected


def _admitted_surface(
    source_handle: str,
    payload: dict[str, object],
    context: RuntimeToolActorContext,
    *,
    data_class: str = "public",
    trust_level: str,
    classification_revision: int = HOSTED_TOOL_RESULT_ADMISSION_REVISION,
    authority_ref: str = "",
    classification_authority=None,
) -> RuntimeToolSurfaceResult:
    digest = _payload_digest(payload)
    return RuntimeToolSurfaceResult(
        payload,
        validated_classification(
            data_class=data_class,
            provenance="tool_result",
            trust_level=trust_level,
            source_ref=(
                f"core-hosted-tool-result:{source_handle}{authority_ref}"
            ),
            source_revision=digest,
            source_digest=digest,
            resource_identity=(
                "core-hosted-tool-result:"
                f"{context.workspace_id}:{context.session_id}:"
                f"{source_handle}:{digest}"
            ),
            classification_revision=classification_revision,
            classification_authority_id=str(
                getattr(
                    classification_authority,
                    "classification_authority_id",
                    "",
                )
                or ""
            ),
            classification_authority_kind=str(
                getattr(
                    classification_authority,
                    "classification_authority_kind",
                    "",
                )
                or ""
            ),
            classification_authority_ref=str(
                getattr(
                    classification_authority,
                    "classification_authority_ref",
                    "",
                )
                or ""
            ),
            classification_authority_revision=getattr(
                classification_authority,
                "classification_authority_revision",
                None,
            ),
            classification_authority_digest=str(
                getattr(
                    classification_authority,
                    "classification_authority_digest",
                    "",
                )
                or ""
            ),
            classification_authority_policy_revision=str(
                getattr(
                    classification_authority,
                    "classification_authority_policy_revision",
                    "",
                )
                or ""
            ),
            classification_authority_bound=(
                classification_authority is not None
            ),
        ),
    )


def _payload_digest(payload: dict[str, object]) -> str:
    return content_sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _public_authority(resolver, context):
    if not callable(resolver):
        return None
    try:
        authority = resolver(context.workspace_id)
    except Exception:
        return None
    return (
        authority
        if runtime_public_content_authority_is_active(
            authority,
            workspace_id=context.workspace_id,
        )
        else None
    )


def _cli_definition(registry, command_id: str):
    try:
        return registry.get_command(command_id)
    except Exception:
        return None


def _mcp_definition(registry, tool_name: str):
    try:
        return registry.get_tool(tool_name)
    except Exception:
        return None


def _definition_has_public_result_authority(definition) -> bool:
    return bool(
        getattr(definition, "owner_kind", None) == "core"
        and getattr(definition, "schema_public", False) is True
        and getattr(definition, "certified_tcb_component", None)
        == _CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT
        and getattr(definition, "agentic_result_data_class", None) == "public"
    )


def _discovery_has_public_authority(
    handle,
    result,
    *,
    cli_registry,
    mcp_registry,
) -> bool:
    collection, identity_field, resolver = (
        ("commands", "command_id", lambda value: _cli_definition(cli_registry, value))
        if handle == "core-capability:cli.list"
        else ("tools", "tool_name", lambda value: _mcp_definition(mcp_registry, value))
    )
    items = result.get(collection)
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        identity = item.get(identity_field)
        if not isinstance(identity, str):
            return False
        definition = resolver(identity)
        if (
            definition is None
            or getattr(definition, "owner_kind", None) != "core"
            or getattr(definition, "schema_public", False) is not True
            or getattr(definition, "certified_tcb_component", None)
            != _CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT
            or item.get("owner_kind", "core") != "core"
            or item.get("agentic_result_projection")
            != getattr(definition, "agentic_result_projection", None)
            or (
                item.get("agentic_result_projection") is not None
                and not definition_has_certified_result_projection(definition)
            )
        ):
            return False
    return True


__all__ = ["HOSTED_TOOL_RESULT_ADMISSION_REVISION"]
