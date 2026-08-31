"""Operator CLI commands for hosted-runtime public content authority."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.cli.core_command_helpers import OPERATOR_ONLY, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.runtime.public_content_authority_store import (
    issue_runtime_public_content_authority,
    revoke_runtime_public_content_authority,
    runtime_public_content_authority_projection,
    runtime_public_content_authority_record_for_workspace,
)
from core.workspaces.errors import WorkspaceDataGovernanceError
from core.workspaces.store import WorkspaceStore


def runtime_public_content_command_specs(
    *,
    workspace_store: WorkspaceStore | None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build the closed operator-only authority workflow."""

    def status(
        arguments: dict[str, Any],
        context: CliInvocationContext,
    ) -> dict[str, Any]:
        command_id = "core.providers.agentic.public-content.status"
        workspace_id = _workspace_id(arguments, context)
        error = _common_error(command_id, workspace_store, workspace_id)
        if error is not None:
            return error
        record = runtime_public_content_authority_record_for_workspace(
            workspace_store,
            workspace_id,
        )
        return _projection(command_id, workspace_id, record)

    def issue(
        arguments: dict[str, Any],
        context: CliInvocationContext,
    ) -> dict[str, Any]:
        command_id = "core.providers.agentic.public-content.issue"
        workspace_id = _workspace_id(arguments, context)
        error = _mutation_error(
            command_id,
            workspace_store,
            workspace_id,
            context,
        )
        if error is not None:
            return error
        if arguments.get("confirmation") != "public-workspace-content-reviewed":
            return {
                "command_id": command_id,
                "error": "runtime_public_content_authority_confirmation_required",
            }
        try:
            record = issue_runtime_public_content_authority(
                workspace_store,
                workspace_id=workspace_id,
                actor_id=str(context.user_id).strip(),
                expected_revision=int(arguments.get("expected_revision", -1)),
            )
        except (TypeError, ValueError, WorkspaceDataGovernanceError) as error:
            return {"command_id": command_id, "error": str(error)}
        return _projection(command_id, workspace_id, record)

    def revoke(
        arguments: dict[str, Any],
        context: CliInvocationContext,
    ) -> dict[str, Any]:
        command_id = "core.providers.agentic.public-content.revoke"
        workspace_id = _workspace_id(arguments, context)
        error = _mutation_error(
            command_id,
            workspace_store,
            workspace_id,
            context,
        )
        if error is not None:
            return error
        try:
            record = revoke_runtime_public_content_authority(
                workspace_store,
                workspace_id=workspace_id,
                actor_id=str(context.user_id).strip(),
                expected_revision=int(arguments.get("expected_revision", -1)),
                reason=str(arguments.get("reason") or ""),
            )
        except (TypeError, ValueError, WorkspaceDataGovernanceError) as error:
            return {"command_id": command_id, "error": str(error)}
        return _projection(command_id, workspace_id, record)

    return [
        (
            _definition(
                action="status",
                description=(
                    "Inspect the operator-owned public hosted-runtime content "
                    "authority."
                ),
                argument_schema={
                    "type": "object",
                    "properties": {"workspace_id": {"type": "string"}},
                    "additionalProperties": False,
                },
                effect_class="read",
                safe_to_retry=True,
            ),
            status,
        ),
        (
            _definition(
                action="issue",
                description=(
                    "Classify one workspace's hosted-runtime content as public."
                ),
                argument_schema={
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "expected_revision": {
                            "type": "integer",
                            "minimum": 0,
                        },
                        "confirmation": {
                            "type": "string",
                            "enum": ["public-workspace-content-reviewed"],
                        },
                    },
                    "required": ["expected_revision", "confirmation"],
                    "additionalProperties": False,
                },
                effect_class="mutating",
                safe_to_retry=False,
            ),
            issue,
        ),
        (
            _definition(
                action="revoke",
                description=(
                    "Revoke one public hosted-runtime content classification."
                ),
                argument_schema={
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "expected_revision": {
                            "type": "integer",
                            "minimum": 1,
                        },
                        "reason": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 512,
                        },
                    },
                    "required": ["expected_revision", "reason"],
                    "additionalProperties": False,
                },
                effect_class="mutating",
                safe_to_retry=False,
            ),
            revoke,
        ),
    ]


def _definition(
    *,
    action: str,
    description: str,
    argument_schema: dict[str, object],
    effect_class: str,
    safe_to_retry: bool,
) -> CliCommandDefinition:
    return replace(
        core_cli_command(
            command_id=f"core.providers.agentic.public-content.{action}",
            path_segments=[
                "core",
                "providers",
                "agentic",
                "public-content",
                action,
            ],
            description=description,
            owner_id="providers",
            invocation_policy=OPERATOR_ONLY,
            argument_schema=argument_schema,
        ),
        effect_class=effect_class,
        supports_idempotency=False,
        safe_to_retry=safe_to_retry,
    )


def _workspace_id(arguments, context) -> str:
    return str(arguments.get("workspace_id") or context.workspace_id or "").strip()


def _common_error(command_id, workspace_store, workspace_id):
    if workspace_store is None:
        return {
            "command_id": command_id,
            "error": "data_governance_store_unavailable",
        }
    if not workspace_id:
        return {"command_id": command_id, "error": "workspace_id_required"}
    return None


def _mutation_error(command_id, workspace_store, workspace_id, context):
    error = _common_error(command_id, workspace_store, workspace_id)
    if error is not None:
        return error
    if not str(context.user_id or "").strip():
        return {"command_id": command_id, "error": "operator_actor_required"}
    return None


def _projection(command_id, workspace_id, record):
    return {
        "command_id": command_id,
        "workspace_id": workspace_id,
        "public_content_authority": runtime_public_content_authority_projection(
            record,
            workspace_id=workspace_id,
        ),
    }


__all__ = ["runtime_public_content_command_specs"]
