"""Core-owned admission and safe projection for hosted tool results."""

from __future__ import annotations

from typing import Callable

from core.egress.classification import CanonicalSourceClassification
from core.runtime.hosted_tool_result_authority import (
    HOSTED_TOOL_RESULT_ADMISSION_REVISION,
    _admitted_surface,
    _cli_definition,
    _content_derived_surface,
    _definition_has_public_result_authority,
    _discovery_has_public_authority,
    _mcp_definition,
    _public_authority,
)
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolResultPreflightDecision,
    RuntimeToolSurfaceResult,
)


HOSTED_TOOL_RESULT_PREFLIGHT_REVISION = 2

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
    public_content_authority_resolver=None,
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
            return _content_derived_surface(
                handle,
                result,
                context,
                public_content_authority=_public_authority(
                    public_content_authority_resolver,
                    context,
                ),
            )
        if handle in {
            "core-capability:cli.list",
            "core-capability:mcp.list",
        }:
            return _content_derived_surface(
                handle,
                dict(result),
                context,
                core_session_token_fields=True,
                declared_public=_discovery_has_public_authority(
                    handle,
                    result,
                    cli_registry=cli_registry,
                    mcp_registry=mcp_registry,
                ),
                public_content_authority=_public_authority(
                    public_content_authority_resolver,
                    context,
                ),
            )
        if handle == "core-capability:cli.run" or handle.startswith("cli:"):
            command_id = (
                str(arguments.get("command_id") or "").strip()
                if handle == "core-capability:cli.run"
                else handle.removeprefix("cli:")
            )
            definition = _cli_definition(cli_registry, command_id)
            if definition is None:
                return None
            return _content_derived_surface(
                f"cli:{command_id}",
                dict(result),
                context,
                declared_public=_definition_has_public_result_authority(
                    definition
                ),
                public_content_authority=_public_authority(
                    public_content_authority_resolver,
                    context,
                ),
            )
        if handle == "core-capability:mcp.call" or handle.startswith("mcp:"):
            tool_name = (
                str(arguments.get("tool_name") or "").strip()
                if handle == "core-capability:mcp.call"
                else handle.removeprefix("mcp:")
            )
            definition = _mcp_definition(mcp_registry, tool_name)
            if definition is None:
                return None
            return _content_derived_surface(
                f"mcp:{tool_name}",
                dict(result),
                context,
                declared_public=_definition_has_public_result_authority(
                    definition
                ),
                public_content_authority=_public_authority(
                    public_content_authority_resolver,
                    context,
                ),
            )
        return None

    return resolve


def build_hosted_tool_result_preflight_resolver(
    *,
    cli_registry,
    mcp_registry,
    process_registry=None,
    public_content_authority_resolver=None,
):
    """Fence variable-result mutations that cannot guarantee safe pairing."""
    admitted_read = RuntimeToolResultPreflightDecision(True)
    admitted_public = RuntimeToolResultPreflightDecision(True, "public")
    admitted_guarded = RuntimeToolResultPreflightDecision(True)
    denied = RuntimeToolResultPreflightDecision(False)

    def resolve(handle, arguments, context):
        if handle == "core-capability:shell.run":
            if not arguments.get("mutation_scopes"):
                return admitted_read
            return (
                admitted_guarded
                if _public_authority(
                    public_content_authority_resolver,
                    context,
                )
                is not None
                else denied
            )
        if handle == "core-capability:process.start":
            return admitted_public
        if handle == "core-capability:process.status":
            if process_registry is None:
                return denied
            pending = process_registry.has_pending_workspace_effects(
                process_id=str(arguments.get("process_id") or ""),
                session_id=context.session_id,
                workspace_id=context.workspace_id,
            )
            if not pending:
                return admitted_read
            return (
                admitted_guarded
                if _public_authority(
                    public_content_authority_resolver,
                    context,
                )
                is not None
                else denied
            )
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
                admitted_public=admitted_public,
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
                admitted_public=admitted_public,
                denied=denied,
            )
        return None

    return resolve


def _definition_preflight(
    definition,
    *,
    admitted_read,
    admitted_public,
    denied,
):
    if definition is None:
        return denied
    if getattr(definition, "effect_class", None) == "read":
        return admitted_read
    return (
        admitted_public
        if _definition_has_public_result_authority(definition)
        else denied
    )


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


__all__ = [
    "HOSTED_TOOL_RESULT_ADMISSION_REVISION",
    "HOSTED_TOOL_RESULT_PREFLIGHT_REVISION",
    "build_hosted_tool_result_admission_resolver",
    "build_hosted_tool_result_preflight_resolver",
]
