"""Core-owned admission and safe projection for hosted tool results."""

from __future__ import annotations

import json
from typing import Callable

from core.egress.classification import (
    CanonicalSourceClassification,
    content_sha256,
    validated_classification,
)
from core.runtime.content_data_classification import classify_runtime_content
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolResultPreflightDecision,
    RuntimeToolSurfaceResult,
)


HOSTED_TOOL_RESULT_ADMISSION_REVISION = 3
HOSTED_TOOL_RESULT_PREFLIGHT_REVISION = 1

_ACTION_METADATA_FIELDS: dict[str, tuple[str, ...]] = {
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
        if handle in {
            "core-capability:shell.run",
            "core-capability:process.status",
        }:
            return _content_derived_surface(handle, result, context)
        if handle in {
            "core-capability:cli.list",
            "core-capability:mcp.list",
        }:
            return _content_derived_surface(
                handle,
                dict(result),
                context,
                core_session_token_fields=True,
            )
        if handle == "core-capability:cli.run" or handle.startswith("cli:"):
            command_id = (
                str(arguments.get("command_id") or "").strip()
                if handle == "core-capability:cli.run"
                else handle.removeprefix("cli:")
            )
            if _cli_definition(cli_registry, command_id) is None:
                return None
            return _content_derived_surface(
                f"cli:{command_id}",
                dict(result),
                context,
            )
        if handle == "core-capability:mcp.call" or handle.startswith("mcp:"):
            tool_name = (
                str(arguments.get("tool_name") or "").strip()
                if handle == "core-capability:mcp.call"
                else handle.removeprefix("mcp:")
            )
            if _mcp_definition(mcp_registry, tool_name) is None:
                return None
            return _content_derived_surface(
                f"mcp:{tool_name}",
                dict(result),
                context,
            )
        return None

    return resolve


def build_hosted_tool_result_preflight_resolver(
    *,
    cli_registry,
    mcp_registry,
    process_registry=None,
):
    """Fence variable-result mutations that cannot guarantee safe pairing."""
    admitted_read = RuntimeToolResultPreflightDecision(True)
    admitted_public = RuntimeToolResultPreflightDecision(True, "public")
    denied = RuntimeToolResultPreflightDecision(False)

    def resolve(handle, arguments, context):
        if handle == "core-capability:shell.run":
            return admitted_read if not arguments.get("mutation_scopes") else denied
        if handle == "core-capability:process.start":
            return admitted_public if not arguments.get("mutation_scopes") else denied
        if handle == "core-capability:process.status":
            if process_registry is None:
                return denied
            pending = process_registry.has_pending_workspace_effects(
                process_id=str(arguments.get("process_id") or ""),
                session_id=context.session_id,
                workspace_id=context.workspace_id,
            )
            return denied if pending else admitted_read
        if handle in {
            "core-capability:process.input",
            "core-capability:process.interrupt",
        }:
            return admitted_public
        if handle in {
            "core-capability:cli.list",
            "core-capability:mcp.list",
        }:
            return admitted_read
        if handle == "core-capability:cli.run" or handle.startswith("cli:"):
            command_id = (
                str(arguments.get("command_id") or "").strip()
                if handle == "core-capability:cli.run"
                else handle.removeprefix("cli:")
            )
            return _definition_preflight(
                _cli_definition(cli_registry, command_id),
                admitted_read=admitted_read,
                denied=denied,
            )
        if handle == "core-capability:mcp.call" or handle.startswith("mcp:"):
            tool_name = (
                str(arguments.get("tool_name") or "").strip()
                if handle == "core-capability:mcp.call"
                else handle.removeprefix("mcp:")
            )
            return _definition_preflight(
                _mcp_definition(mcp_registry, tool_name),
                admitted_read=admitted_read,
                denied=denied,
            )
        return None

    return resolve


def _definition_preflight(definition, *, admitted_read, denied):
    if definition is None:
        return denied
    return admitted_read if getattr(definition, "effect_class", None) == "read" else denied


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


def _content_derived_surface(
    source_handle: str,
    payload: dict[str, object],
    context: RuntimeToolActorContext,
    *,
    core_session_token_fields: bool = False,
) -> RuntimeToolSurfaceResult:
    classification_payload = (
        _without_core_session_tokens(payload)
        if core_session_token_fields
        else payload
    )
    return _admitted_surface(
        source_handle,
        payload,
        context,
        data_class=classify_runtime_content(
            classification_payload,
            content_type=(
                "text/plain"
                if core_session_token_fields
                else "application/json"
            ),
        ),
        trust_level="untrusted_tool_output",
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
            data_class=data_class,
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
    "HOSTED_TOOL_RESULT_PREFLIGHT_REVISION",
    "build_hosted_tool_result_admission_resolver",
    "build_hosted_tool_result_preflight_resolver",
]
