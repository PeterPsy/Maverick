"""Secret-management core CLI commands."""

from __future__ import annotations

from typing import Any

from core.cli.core_command_helpers import OPERATOR_ONLY, core_cli_command, record_cli_audit
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.secrets.service import create_platform_secret, disable_platform_secret, revoke_platform_secret, rotate_platform_secret
from core.secrets.store import SecretStore


def secret_command_specs(
    *,
    secret_store: SecretStore | None = None,
    observability_store=None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build platform secret command specs."""
    def _secrets_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"secrets": []}
        return {
            "command_id": "core.secrets.list",
            "secrets": [
                {"secret_id": item.secret_id, "alias": item.alias, "label": item.label, "status": item.status}
                for item in secret_store.list_secrets()
            ],
        }

    def _secret_bindings_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"bindings": []}
        workspace_id = arguments.get("workspace_id") or context.workspace_id
        return {
            "command_id": "core.secrets.bindings.list",
            "bindings": [
                {
                    "binding_id": item.binding_id,
                    "scope": item.scope,
                    "workspace_id": item.workspace_id,
                    "app_id": item.app_id,
                    "provider_id": item.provider_id,
                    "logical_name": item.logical_name,
                    "secret_ref": item.secret_ref,
                    "status": item.status,
                }
                for item in secret_store.list_secret_bindings(
                    workspace_id=workspace_id,
                    app_id=arguments.get("app_id"),
                    provider_id=arguments.get("provider_id"),
                )
            ],
        }

    def _secret_create_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"created": False}
        secret = create_platform_secret(
            secret_store,
            label=str(arguments["label"]),
            raw_value=str(arguments["raw_value"]),
            alias=None if arguments.get("alias") is None else str(arguments["alias"]),
            description=None if arguments.get("description") is None else str(arguments["description"]),
        )
        record_cli_audit(
            observability_store,
            action="core.secrets.create",
            detail=f"Created platform secret `{secret.secret_id}`.",
            payload={"secret_id": secret.secret_id, "alias": secret.alias},
        )
        return {
            "command_id": "core.secrets.create",
            "created": True,
            "secret": {"secret_id": secret.secret_id, "alias": secret.alias, "label": secret.label, "status": secret.status},
        }

    def _secret_rotate_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"rotated": False}
        secret = rotate_platform_secret(secret_store, secret_id=str(arguments["secret_id"]), raw_value=str(arguments["raw_value"]))
        record_cli_audit(
            observability_store,
            action="core.secrets.rotate",
            detail=f"Rotated platform secret `{secret.secret_id}`.",
            payload={"secret_id": secret.secret_id},
        )
        return {
            "command_id": "core.secrets.rotate",
            "rotated": True,
            "secret": {"secret_id": secret.secret_id, "alias": secret.alias, "label": secret.label, "status": secret.status},
        }

    def _secret_disable_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"disabled": False}
        secret = disable_platform_secret(secret_store, secret_id=str(arguments["secret_id"]))
        record_cli_audit(
            observability_store,
            action="core.secrets.disable",
            detail=f"Disabled platform secret `{secret.secret_id}`.",
            payload={"secret_id": secret.secret_id},
        )
        return {"command_id": "core.secrets.disable", "disabled": True, "secret_id": secret.secret_id, "status": secret.status}

    def _secret_revoke_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if secret_store is None:
            return {"revoked": False}
        secret = revoke_platform_secret(secret_store, secret_id=str(arguments["secret_id"]))
        record_cli_audit(
            observability_store,
            action="core.secrets.revoke",
            detail=f"Revoked platform secret `{secret.secret_id}`.",
            payload={"secret_id": secret.secret_id},
        )
        return {"command_id": "core.secrets.revoke", "revoked": True, "secret_id": secret.secret_id, "status": secret.status}

    command_specs = [
        ("core.secrets.list", ["core", "secrets", "list"], "Inspect platform secret metadata without raw values.", _secrets_list_handler),
        ("core.secrets.bindings.list", ["core", "secrets", "bindings", "list"], "Inspect secret binding metadata without raw values.", _secret_bindings_list_handler),
        ("core.secrets.create", ["core", "secrets", "create"], "Create one platform secret without exposing its raw value in the result.", _secret_create_handler),
        ("core.secrets.rotate", ["core", "secrets", "rotate"], "Rotate one platform secret without exposing the raw value.", _secret_rotate_handler),
        ("core.secrets.disable", ["core", "secrets", "disable"], "Disable one platform secret.", _secret_disable_handler),
        ("core.secrets.revoke", ["core", "secrets", "revoke"], "Revoke one platform secret and remove its raw value.", _secret_revoke_handler),
    ]
    return [
        (
            core_cli_command(
                command_id=command_id,
                path_segments=path_segments,
                description=description,
                owner_id="secrets",
                invocation_policy=OPERATOR_ONLY,
            ),
            handler,
        )
        for command_id, path_segments, description, handler in command_specs
    ]
