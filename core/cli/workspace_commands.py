"""Workspace-oriented core CLI commands."""

from __future__ import annotations

from typing import Any

from core.cli.core_command_helpers import WORKSPACE_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.workspaces.store import WorkspaceStore


def workspace_command_specs(
    *,
    workspace_store: WorkspaceStore | None = None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build workspace inspection command specs."""
    def _workspace_current_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if workspace_store is None or context.workspace_id is None:
            return {"workspace_id": context.workspace_id, "workspace": None}
        workspace = workspace_store.get_workspace(context.workspace_id)
        return {
            "command_id": "core.workspaces.current",
            "workspace_id": context.workspace_id,
            "workspace": {
                "workspace_id": workspace.workspace_id,
                "name": workspace.name,
                "status": workspace.status,
            },
        }

    return [
        (
            core_cli_command(
                command_id="core.workspaces.current",
                path_segments=["core", "workspaces", "current"],
                description="Inspect the current trusted workspace context.",
                owner_id="workspaces",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _workspace_current_handler,
        )
    ]
