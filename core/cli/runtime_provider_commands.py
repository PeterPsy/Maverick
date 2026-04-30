"""Runtime and provider core CLI commands."""

from __future__ import annotations

from typing import Any

from core.cli.core_command_helpers import WORKSPACE_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.providers.store import ProviderStore
from core.runtime.store import RuntimeStore


def runtime_provider_command_specs(
    *,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build runtime and provider command specs."""
    def _runtime_status_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if runtime_store is None or context.workspace_id is None:
            return {"workspace_id": context.workspace_id, "sessions": []}
        return {
            "command_id": "core.runtime.status",
            "workspace_id": context.workspace_id,
            "sessions": [
                {
                    "session_id": item.session_id,
                    "agent_id": item.agent_id,
                    "status": item.status,
                    "effective_mode": item.effective_mode,
                }
                for item in runtime_store.list_sessions(context.workspace_id)
            ],
        }

    def _providers_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"providers": []}
        return {
            "command_id": "core.providers.list",
            "providers": [
                {
                    "provider_id": item.provider_id,
                    "label": item.label,
                    "kind": item.kind,
                    "status": item.status,
                }
                for item in provider_store.list_provider_definitions()
            ],
        }

    return [
        (
            core_cli_command(
                command_id="core.runtime.status",
                path_segments=["core", "runtime", "status"],
                description="Inspect runtime status for the active workspace.",
                owner_id="runtime",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _runtime_status_handler,
        ),
        (
            core_cli_command(
                command_id="core.providers.list",
                path_segments=["core", "providers", "list"],
                description="Inspect configured provider definitions.",
                owner_id="providers",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _providers_list_handler,
        ),
    ]
