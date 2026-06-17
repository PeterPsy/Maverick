"""CLI registry builder and invocation facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.store import AppStore
from core.cli.errors import CliCommandNotFoundError, CliInvocationNotAllowedError
from core.cli.app_commands import _workspace_app_command_specs
from core.cli.app_lifecycle_commands import app_lifecycle_command_specs
from core.cli.command_registry import CliCommandRegistry
from core.cli.core_commands import _core_command_specs
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.cli.runner import CliRunner
from core.identity.store import IdentityStore
from core.inter_agent.store import InterAgentStore
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.recovery.store import RecoveryStore
from core.runtime.store import RuntimeStore
from core.secrets.store import SecretStore
from core.workspaces.store import WorkspaceStore

def build_core_cli_registry(
    *,
    app_store: AppStore | None = None,
    identity_store: IdentityStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    app_event_bus=None,
    workspace_id: str | None = None,
    context: CliInvocationContext | None = None,
    start_path: Path | None = None,
) -> CliCommandRegistry:
    """Build the platform-managed CLI registry for core and enabled app commands."""
    registry = CliCommandRegistry()
    for definition, handler in _core_command_specs(
        app_store=app_store,
        identity_store=identity_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        start_path=start_path,
    ):
        registry.register_command(definition, handler)
    if app_store is not None and workspace_id is not None:
        for definition, handler in _workspace_app_command_specs(
            app_store,
            workspace_id=workspace_id,
            workspace_store=workspace_store,
            provider_store=provider_store,
            runtime_store=runtime_store,
            context=context,
            secret_store=secret_store,
            observability_store=observability_store,
            app_event_bus=app_event_bus,
            start_path=start_path,
        ):
            registry.register_command(definition, handler)
        for definition, handler in app_lifecycle_command_specs(
            app_store=app_store,
            workspace_id=workspace_id,
            start_path=start_path,
            observability_store=observability_store,
            app_event_bus=app_event_bus,
        ):
            registry.register_command(definition, handler)
    return registry

def list_core_cli_commands(
    *,
    app_store: AppStore | None = None,
    identity_store: IdentityStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    app_event_bus=None,
    workspace_id: str | None = None,
    context: CliInvocationContext | None = None,
    start_path: Path | None = None,
) -> list[CliCommandDefinition]:
    """List visible CLI commands for the requested workspace context."""
    return build_core_cli_registry(
        app_store=app_store,
        identity_store=identity_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        app_event_bus=app_event_bus,
        workspace_id=workspace_id,
        context=context,
        start_path=start_path,
    ).list_commands()

def run_core_cli_command(
    *,
    command_id: str,
    context: CliInvocationContext,
    arguments: dict[str, Any] | None = None,
    app_store: AppStore | None = None,
    identity_store: IdentityStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    inter_agent_store: InterAgentStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    app_event_bus=None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> dict[str, Any]:
    """Run one visible CLI command under a trusted invocation context."""
    registry = build_core_cli_registry(
        app_store=app_store,
        identity_store=identity_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        app_event_bus=app_event_bus,
        workspace_id=workspace_id,
        context=context,
        start_path=start_path,
    )
    try:
        return CliRunner(registry).run_command(command_id=command_id, arguments=arguments, context=context)
    except CliCommandNotFoundError:
        if _hidden_app_command_exists(
            command_id=command_id,
            app_store=app_store,
            identity_store=identity_store,
            workspace_store=workspace_store,
            provider_store=provider_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            secret_store=secret_store,
            recovery_store=recovery_store,
            provider_registry=provider_registry,
            observability_store=observability_store,
            app_event_bus=app_event_bus,
            workspace_id=workspace_id,
            start_path=start_path,
        ):
            raise CliInvocationNotAllowedError("This app CLI command is not visible to the caller.") from None
        raise


def _hidden_app_command_exists(
    *,
    command_id: str,
    app_store: AppStore | None,
    identity_store: IdentityStore | None,
    workspace_store: WorkspaceStore | None,
    provider_store: ProviderStore | None,
    runtime_store: RuntimeStore | None,
    inter_agent_store: InterAgentStore | None,
    secret_store: SecretStore | None,
    recovery_store: RecoveryStore | None,
    provider_registry: ProviderRegistry | None,
    observability_store,
    app_event_bus,
    workspace_id: str | None,
    start_path: Path | None,
) -> bool:
    if app_store is None or workspace_id is None:
        return False
    unfiltered = build_core_cli_registry(
        app_store=app_store,
        identity_store=identity_store,
        workspace_store=workspace_store,
        provider_store=provider_store,
        runtime_store=runtime_store,
        inter_agent_store=inter_agent_store,
        secret_store=secret_store,
        recovery_store=recovery_store,
        provider_registry=provider_registry,
        observability_store=observability_store,
        app_event_bus=app_event_bus,
        workspace_id=workspace_id,
        context=None,
        start_path=start_path,
    )
    try:
        definition = unfiltered.get_command(command_id)
    except CliCommandNotFoundError:
        return False
    return definition.owner_kind == "app"
