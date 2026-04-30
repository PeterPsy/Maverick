"""Identity recovery core CLI commands."""

from __future__ import annotations

from typing import Any

from core.cli.core_command_helpers import OPERATOR_ONLY, core_cli_command, record_cli_audit
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.identity.service import bootstrap_default_admin, set_user_password
from core.identity.store import IdentityStore
from core.workspaces.store import WorkspaceStore


def identity_command_specs(
    *,
    identity_store: IdentityStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    observability_store=None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build identity recovery command specs."""
    def _reset_admin_password_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if identity_store is None or workspace_store is None:
            return {"reset": False}
        username = str(arguments.get("username") or "admin").strip()
        password = str(arguments["password"])
        user = bootstrap_default_admin(
            identity_store,
            workspace_store,
            username=username,
            password=None,
        )
        credential = set_user_password(identity_store, user_id=user.user_id, password=password)
        record_cli_audit(
            observability_store,
            action="core.identity.reset-admin-password",
            detail=f"Operator reset password credential for admin `{user.user_id}`.",
            payload={"user_id": user.user_id, "username": user.username},
        )
        return {
            "command_id": "core.identity.reset-admin-password",
            "reset": True,
            "user": {"user_id": user.user_id, "username": user.username, "platform_role": user.platform_role},
            "credential": {"algorithm": credential.algorithm, "updated_at": credential.updated_at.isoformat()},
        }

    return [
        (
            core_cli_command(
                command_id="core.identity.reset-admin-password",
                path_segments=["core", "identity", "reset-admin-password"],
                description="Operator-only recovery action to set the bootstrap admin password.",
                owner_id="identity",
                invocation_policy=OPERATOR_ONLY,
            ),
            _reset_admin_password_handler,
        )
    ]
