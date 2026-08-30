"""Core-owned admission and safe projection for hosted tool results."""

from __future__ import annotations

import json
from typing import Callable

from core.egress.classification import (
    CanonicalSourceClassification,
    content_sha256,
    validated_classification,
)
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_discovery_support import (
    CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT,
)


HOSTED_TOOL_RESULT_ADMISSION_REVISION = 1

_ACTION_METADATA_FIELDS: dict[str, tuple[str, ...]] = {
    "core-capability:filesystem.write": (
        "path",
        "byte_count",
        "created",
        "replaced",
        "previous_resource_revision",
        "previous_resource_digest",
        "resource_identity",
        "resource_revision",
        "resource_digest",
        "instruction_scope_digest",
    ),
    "core-capability:filesystem.move": (
        "source_path",
        "destination_path",
        "resource_identity",
        "resource_revision",
        "resource_digest",
    ),
    "core-capability:filesystem.delete": (
        "path",
        "deleted",
        "recursive",
        "deleted_entry_count",
        "cleanup_pending",
        "cleanup_reason",
        "resource_identity",
        "resource_revision",
        "resource_digest",
    ),
    "core-capability:process.start": (
        "process_id",
        "status",
        "output_offset",
        "workspace_effects_pending",
        "mutation_scope_count",
    ),
    "core-capability:process.input": (
        "process_id",
        "accepted_bytes",
        "stdin_open",
    ),
    "core-capability:process.interrupt": (
        "process_id",
        "status",
        "terminated",
    ),
}


def build_hosted_tool_result_admission_resolver(
    *,
    cli_registry,
    mcp_registry,
) -> Callable[
    [str, dict[str, object], dict[str, object], RuntimeToolActorContext],
    CanonicalSourceClassification | RuntimeToolSurfaceResult | None,
]:
    """Build the closed production policy for result bytes shown to a model."""

    def resolve(handle, arguments, result, context):
        if handle in _ACTION_METADATA_FIELDS:
            projection = _metadata_projection(
                handle,
                result,
                _ACTION_METADATA_FIELDS[handle],
            )
            return _admitted_surface(
                handle,
                projection,
                context,
                trust_level="trusted_platform",
            )
        if handle == "core-capability:shell.run":
            projection = _metadata_projection(
                handle,
                result,
                (
                    "exit_code",
                    "output_bytes",
                    "stream_complete",
                    "workspace_effects_committed",
                    "workspace_effect_count",
                    "mutation_scope_count",
                ),
            )
            projection["output_withheld"] = (
                bool(result.get("output"))
                or result.get("output_withheld") is True
            )
            return _admitted_surface(
                handle,
                projection,
                context,
                trust_level="trusted_platform",
            )
        if handle == "core-capability:process.status":
            projection = _metadata_projection(
                handle,
                result,
                (
                    "process_id",
                    "status",
                    "exit_code",
                    "output_offset",
                    "next_output_offset",
                    "output_pending",
                    "stdin_open",
                    "failure_reason",
                    "output_truncated",
                ),
            )
            projection["output_withheld"] = (
                bool(result.get("output"))
                or result.get("output_withheld") is True
            )
            projection["workspace_effects_withheld"] = (
                result.get("workspace_effects") is not None
                or result.get("workspace_effects_withheld") is True
            )
            return _admitted_surface(
                handle,
                projection,
                context,
                trust_level="trusted_platform",
            )
        if handle in {
            "core-capability:cli.list",
            "core-capability:mcp.list",
        }:
            projection = _discovery_projection(
                handle,
                result,
                cli_registry=cli_registry,
                mcp_registry=mcp_registry,
            )
            return _admitted_surface(
                handle,
                projection,
                context,
                trust_level="trusted_platform",
            )
        if handle == "core-capability:cli.run" or handle.startswith("cli:"):
            command_id = (
                str(arguments.get("command_id") or "").strip()
                if handle == "core-capability:cli.run"
                else handle.removeprefix("cli:")
            )
            definition = _cli_definition(cli_registry, command_id)
            if _public_result_definition(definition):
                return _admitted_surface(
                    f"cli:{command_id}",
                    dict(result),
                    context,
                    trust_level="untrusted_tool_output",
                )
            return _withheld_invocation(
                handle,
                "command_id",
                command_id,
                context,
            )
        if handle == "core-capability:mcp.call" or handle.startswith("mcp:"):
            tool_name = (
                str(arguments.get("tool_name") or "").strip()
                if handle == "core-capability:mcp.call"
                else handle.removeprefix("mcp:")
            )
            definition = _mcp_definition(mcp_registry, tool_name)
            if _public_result_definition(definition):
                return _admitted_surface(
                    f"mcp:{tool_name}",
                    dict(result),
                    context,
                    trust_level="untrusted_tool_output",
                )
            return _withheld_invocation(
                handle,
                "tool_name",
                tool_name,
                context,
            )
        return None

    return resolve


def _metadata_projection(
    handle: str,
    result: dict[str, object],
    fields: tuple[str, ...],
) -> dict[str, object]:
    projection: dict[str, object] = {
        "action": handle,
        "outcome": "succeeded",
    }
    for field_name in fields:
        if field_name in result and _safe_metadata_value(result[field_name]):
            projection[field_name] = result[field_name]
    return projection


def _safe_metadata_value(value: object) -> bool:
    return value is None or isinstance(value, (str, int, bool))


def _withheld_invocation(
    handle: str,
    identity_field: str,
    identity: str,
    context: RuntimeToolActorContext,
) -> RuntimeToolSurfaceResult:
    return _admitted_surface(
        handle,
        {
            "action": handle,
            identity_field: identity,
            "outcome": "succeeded",
            "result_withheld": True,
            "withheld_reason": "tool_result_classification_unavailable",
        },
        context,
        trust_level="trusted_platform",
    )


def _discovery_projection(
    handle: str,
    result: dict[str, object],
    *,
    cli_registry,
    mcp_registry,
) -> dict[str, object]:
    is_cli = handle.endswith("cli.list")
    collection = "commands" if is_cli else "tools"
    identity_field = "command_id" if is_cli else "tool_name"
    raw_items = result.get(collection)
    admitted: list[object] = []
    prior_withheld = result.get("withheld_result_count", 0)
    withheld = (
        prior_withheld
        if isinstance(prior_withheld, int)
        and not isinstance(prior_withheld, bool)
        and prior_withheld >= 0
        else 0
    )
    if isinstance(raw_items, list):
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                withheld += 1
                continue
            identity = str(raw_item.get(identity_field) or "").strip()
            definition = (
                _cli_definition(cli_registry, identity)
                if is_cli
                else _mcp_definition(mcp_registry, identity)
            )
            if _certified_core_definition(definition):
                admitted.append(dict(raw_item))
            else:
                withheld += 1
    return {
        "registry_revision": result.get("registry_revision"),
        collection: admitted,
        "next_cursor": result.get("next_cursor"),
        "discovery_first": result.get("discovery_first") is True,
        "withheld_result_count": withheld,
    }


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


def _certified_core_definition(definition) -> bool:
    return bool(
        definition is not None
        and getattr(definition, "owner_kind", None) == "core"
        and getattr(definition, "schema_public", False) is True
        and getattr(definition, "certified_tcb_component", None)
        == CERTIFIED_TOOL_SCHEMA_TCB_COMPONENT
    )


def _public_result_definition(definition) -> bool:
    return bool(
        _certified_core_definition(definition)
        and getattr(definition, "agentic_result_data_class", None) == "public"
    )


def _admitted_surface(
    source_handle: str,
    payload: dict[str, object],
    context: RuntimeToolActorContext,
    *,
    trust_level: str,
) -> RuntimeToolSurfaceResult:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = content_sha256(encoded)
    return RuntimeToolSurfaceResult(
        payload,
        validated_classification(
            data_class="public",
            provenance="tool_result",
            trust_level=trust_level,
            source_ref=f"core-hosted-tool-result:{source_handle}",
            source_revision=digest,
            source_digest=digest,
            resource_identity=(
                "core-hosted-tool-result:"
                f"{context.workspace_id}:{context.session_id}:"
                f"{source_handle}:{digest}"
            ),
            classification_revision=HOSTED_TOOL_RESULT_ADMISSION_REVISION,
        ),
    )


__all__ = [
    "HOSTED_TOOL_RESULT_ADMISSION_REVISION",
    "build_hosted_tool_result_admission_resolver",
]
