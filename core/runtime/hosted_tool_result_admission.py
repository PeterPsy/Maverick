"""Core-owned admission and safe projection for hosted tool results."""

from __future__ import annotations

from typing import Callable

from core.egress.classification import CanonicalSourceClassification
from core.runtime.hosted_app_effect_authority import (
    app_read_effect_has_core_audit_authority,
)
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
from core.runtime.hosted_tool_result_projections import (
    certified_tool_result_classification_projection,
    definition_has_certified_result_projection,
    project_certified_tool_result,
)
from core.runtime.tool_discovery_authority import (
    authenticated_discovery_classification_projection,
)
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolResultPreflightDecision,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_result_classification import (
    RuntimeToolClassificationProjection,
)
from core.shared.tool_effects import resolve_tool_effect_class


HOSTED_TOOL_RESULT_PREFLIGHT_REVISION = 5

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
                classification_projection=(
                    _core_managed_classification_projection(
                        handle,
                        projection,
                    )
                ),
            )
        if handle in {
            "core-capability:shell.run",
            "core-capability:process.status",
        }:
            return _content_derived_surface(
                handle,
                result,
                context,
                classification_projection=(
                    _core_managed_classification_projection(
                        handle,
                        result,
                    )
                ),
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
                classification_projection=(
                    authenticated_discovery_classification_projection(
                        handle,
                        dict(result),
                        session_id=context.session_id,
                    )
                ),
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
            projection = project_certified_tool_result(definition, dict(result))
            if projection is not None:
                return _admitted_surface(
                    f"cli:{command_id}",
                    projection,
                    context,
                    trust_level="trusted_platform",
                    classification_projection=(
                        certified_tool_result_classification_projection(
                            definition,
                            projection,
                        )
                    ),
                )
            if definition_has_certified_result_projection(definition):
                return _invalid_projection_surface(
                    f"cli:{command_id}",
                    definition,
                    context,
                )
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
            projection = project_certified_tool_result(definition, dict(result))
            if projection is not None:
                return _admitted_surface(
                    f"mcp:{tool_name}",
                    projection,
                    context,
                    trust_level="trusted_platform",
                    classification_projection=(
                        certified_tool_result_classification_projection(
                            definition,
                            projection,
                        )
                    ),
                )
            if definition_has_certified_result_projection(definition):
                return _invalid_projection_surface(
                    f"mcp:{tool_name}",
                    definition,
                    context,
                )
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
                arguments=_surface_arguments(handle, arguments),
                surface="cli",
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
                arguments=_surface_arguments(handle, arguments),
                surface="mcp",
                admitted_read=admitted_read,
                admitted_public=admitted_public,
                denied=denied,
            )
        return None

    return resolve


def _definition_preflight(
    definition,
    *,
    arguments,
    surface,
    admitted_read,
    admitted_public,
    denied,
):
    if definition is None or not isinstance(arguments, dict):
        return denied
    if definition_has_certified_result_projection(definition):
        return admitted_public
    if resolve_tool_effect_class(definition, arguments) == "read":
        if getattr(definition, "owner_kind", None) == "core":
            return admitted_read
        if app_read_effect_has_core_audit_authority(
            definition,
            arguments,
            surface=surface,
        ):
            return admitted_read
        return denied
    return (
        admitted_public
        if _definition_has_public_result_authority(definition)
        else denied
    )


def _surface_arguments(
    handle: str,
    arguments: dict[str, object],
) -> dict[str, object] | None:
    if handle in {"core-capability:cli.run", "core-capability:mcp.call"}:
        if "arguments" not in arguments:
            return {}
        nested = arguments.get("arguments")
        return nested if isinstance(nested, dict) else None
    return arguments


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


def _invalid_projection_surface(
    source_handle: str,
    definition,
    context: RuntimeToolActorContext,
) -> RuntimeToolSurfaceResult:
    """Fail closed without retaining any bytes from an invalid tool result."""
    return _admitted_surface(
        source_handle,
        {
            "projection_contract": str(definition.agentic_result_projection),
            "outcome": "invalid_tool_result",
        },
        context,
        trust_level="trusted_platform",
    )


def _safe_metadata_value(value: object) -> bool:
    return value is None or isinstance(value, (str, int, bool))


def _core_managed_classification_projection(
    handle: str,
    payload: dict[str, object],
) -> RuntimeToolClassificationProjection | None:
    """Bind omissions to fields minted by exact Core process/shell surfaces."""
    omitted_paths: list[tuple[str | int, ...]] = []
    if handle.startswith("core-capability:process.") and "process_id" in payload:
        omitted_paths.append(("process_id",))
    if handle == "core-capability:shell.run" and "mutation_scope_digest" in payload:
        omitted_paths.append(("mutation_scope_digest",))
    workspace_effects = payload.get("workspace_effects")
    if (
        handle == "core-capability:process.status"
        and isinstance(workspace_effects, dict)
        and "mutation_scope_digest" in workspace_effects
    ):
        omitted_paths.append(("workspace_effects", "mutation_scope_digest"))
    return (
        RuntimeToolClassificationProjection.bind(
            payload,
            omitted_paths=tuple(omitted_paths),
        )
        if omitted_paths
        else None
    )


__all__ = [
    "HOSTED_TOOL_RESULT_ADMISSION_REVISION",
    "HOSTED_TOOL_RESULT_PREFLIGHT_REVISION",
    "build_hosted_tool_result_admission_resolver",
    "build_hosted_tool_result_preflight_resolver",
]
