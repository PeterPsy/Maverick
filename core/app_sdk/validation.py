"""SDK-level app source completeness checks."""

from __future__ import annotations

from pathlib import Path

from core.app_sdk.models import AppSdkValidationIssue
from core.apps.models import ParsedAppContract


REFERENCE_TOOL_SUFFIXES = (
    "reference_manifest",
    "reference_search",
    "reference_resolve",
    "reference_summarize",
)
STANDARD_VIEW_STATE_ACTIONS = (
    "view_filter",
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
)


def validate_app_source_completeness(app_root: Path, parsed: ParsedAppContract) -> list[AppSdkValidationIssue]:
    """Return SDK completeness issues for one parsed app source tree."""
    contract = parsed.contract
    capabilities = contract.capabilities
    entrypoints = contract.entrypoints
    issues: list[AppSdkValidationIssue] = []

    _validate_surface_alignment(parsed, issues)
    _validate_skills(app_root, parsed, issues)

    if entrypoints.mcp:
        _validate_mcp_reference_manifest(parsed, issues)
    if capabilities.reference_entities:
        _validate_reference_entities(parsed, issues)
    if capabilities.view_surfaces:
        _validate_view_surfaces(parsed, issues)
    if capabilities.data_events and not (entrypoints.backend or entrypoints.cli or entrypoints.mcp):
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.data_events",
                message="Declared data events require at least one executable surface: backend, CLI, or MCP.",
            )
        )
    if _has_resource(parsed, "view-state") and not capabilities.view_surfaces:
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.data_events",
                message="The `view-state` data event requires at least one declared view surface.",
            )
        )
    return issues


def _validate_surface_alignment(parsed: ParsedAppContract, issues: list[AppSdkValidationIssue]) -> None:
    capabilities = parsed.contract.capabilities
    entrypoints = parsed.contract.entrypoints
    if capabilities.mcp_tools and not entrypoints.mcp:
        issues.append(
            AppSdkValidationIssue(
                field="entrypoints.mcp",
                message="Declared MCP tools require an `entrypoints.mcp` executable surface.",
            )
        )
    if entrypoints.mcp and not capabilities.mcp_tools:
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.mcp_tools",
                message="An MCP entrypoint must declare the MCP tools it exposes.",
            )
        )
    if capabilities.cli_commands and not entrypoints.cli:
        issues.append(
            AppSdkValidationIssue(
                field="entrypoints.cli",
                message="Declared CLI commands require an `entrypoints.cli` executable surface.",
            )
        )
    if entrypoints.cli and not capabilities.cli_commands:
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.cli_commands",
                message="A CLI entrypoint must declare the CLI commands it exposes.",
            )
        )
    if capabilities.views and not entrypoints.frontend:
        issues.append(
            AppSdkValidationIssue(
                field="entrypoints.frontend",
                message="Declared views require an `entrypoints.frontend` mounted view surface.",
            )
        )
    if capabilities.skills and not entrypoints.skills_root:
        issues.append(
            AppSdkValidationIssue(
                field="entrypoints.skills_root",
                message="Declared bundled skills require an `entrypoints.skills_root` directory.",
            )
        )
    if entrypoints.skills_root and not capabilities.skills:
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.skills",
                message="A skills_root entrypoint must declare the bundled skill ids it exposes.",
            )
        )


def _validate_skills(app_root: Path, parsed: ParsedAppContract, issues: list[AppSdkValidationIssue]) -> None:
    skills_root = parsed.contract.entrypoints.skills_root
    if not skills_root:
        return
    root = app_root / skills_root
    bundled = sorted(path.parent.name for path in root.glob("*/SKILL.md"))
    declared = sorted(parsed.contract.capabilities.skills)
    if declared != bundled:
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.skills",
                message=(
                    "Declared skill ids must match bundled templates under skills_root "
                    f"(declared={declared}, bundled={bundled})."
                ),
            )
        )


def _validate_mcp_reference_manifest(parsed: ParsedAppContract, issues: list[AppSdkValidationIssue]) -> None:
    manifest_tool = f"{_tool_prefix(parsed.app_id)}_reference_manifest"
    if manifest_tool not in set(parsed.contract.capabilities.mcp_tools):
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.mcp_tools",
                message=f"MCP apps must expose the common reference manifest tool `{manifest_tool}`.",
            )
        )


def _validate_reference_entities(parsed: ParsedAppContract, issues: list[AppSdkValidationIssue]) -> None:
    capabilities = parsed.contract.capabilities
    entrypoints = parsed.contract.entrypoints
    if not entrypoints.mcp:
        issues.append(
            AppSdkValidationIssue(
                field="entrypoints.mcp",
                message="Apps with reference_entities must expose the reference MCP surface.",
            )
        )
    if not entrypoints.cli or not capabilities.cli_commands:
        issues.append(
            AppSdkValidationIssue(
                field="entrypoints.cli",
                message="Apps with reference_entities must expose an equivalent CLI surface.",
            )
        )
    if not capabilities.view_surfaces:
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.view_surfaces",
                message="Apps with reference_entities must declare persisted view surfaces for those entities.",
            )
        )
    tools = set(capabilities.mcp_tools)
    tool_prefix = _tool_prefix(parsed.app_id)
    missing_tools = [
        f"{tool_prefix}_{suffix}"
        for suffix in REFERENCE_TOOL_SUFFIXES
        if f"{tool_prefix}_{suffix}" not in tools
    ]
    if missing_tools:
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.mcp_tools",
                message=f"Apps with reference_entities are missing MCP reference tools: {missing_tools}.",
            )
        )


def _validate_view_surfaces(parsed: ParsedAppContract, issues: list[AppSdkValidationIssue]) -> None:
    capabilities = parsed.contract.capabilities
    if not _has_resource(parsed, "view-state"):
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.data_events",
                message="Apps with view_surfaces must declare a `view-state` data event.",
            )
        )
    if not (
        parsed.contract.entrypoints.backend
        or parsed.contract.entrypoints.cli
        or parsed.contract.entrypoints.mcp
    ):
        issues.append(
            AppSdkValidationIssue(
                field="capabilities.view_surfaces",
                message=(
                    "Apps with view_surfaces require at least one executable "
                    "surface to read and mutate view state."
                ),
            )
        )
    tools = set(capabilities.mcp_tools)
    tool_prefix = _tool_prefix(parsed.app_id)
    for surface in capabilities.view_surfaces:
        actions_by_name = {item.action: item for item in surface.state_actions}
        missing_actions = [action for action in STANDARD_VIEW_STATE_ACTIONS if action not in actions_by_name]
        if missing_actions:
            issues.append(
                AppSdkValidationIssue(
                    field=f"capabilities.view_surfaces.{surface.view_id}.state_actions",
                    message=(
                        f"View surface `{surface.view_id}` is missing standard "
                        f"view-state actions: {missing_actions}."
                    ),
                )
            )
        nonstandard_actions = [
            action
            for action in STANDARD_VIEW_STATE_ACTIONS
            if action in actions_by_name and not actions_by_name[action].standard
        ]
        if nonstandard_actions:
            issues.append(
                AppSdkValidationIssue(
                    field=f"capabilities.view_surfaces.{surface.view_id}.state_actions",
                    message=(
                        f"View surface `{surface.view_id}` marks shared actions "
                        f"as non-standard: {nonstandard_actions}."
                    ),
                )
            )
        if parsed.contract.entrypoints.mcp:
            missing_tools = [
                f"{tool_prefix}_{action}"
                for action in STANDARD_VIEW_STATE_ACTIONS
                if f"{tool_prefix}_{action}" not in tools
            ]
            if missing_tools:
                issues.append(
                    AppSdkValidationIssue(
                        field="capabilities.mcp_tools",
                        message=f"View surface `{surface.view_id}` is missing matching MCP tools: {missing_tools}.",
                    )
                )


def _has_resource(parsed: ParsedAppContract, resource: str) -> bool:
    return any(event.resource == resource for event in parsed.contract.capabilities.data_events)


def _tool_prefix(app_id: str) -> str:
    return app_id.replace("-", "_")
