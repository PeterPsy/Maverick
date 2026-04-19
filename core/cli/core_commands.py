"""Core-owned CLI command composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.apps.store import AppStore
from core.cli.models import CliCommandDefinition
from core.cli.recovery_commands import recovery_command_specs
from core.cli.runtime_provider_commands import runtime_provider_command_specs
from core.cli.secret_commands import secret_command_specs
from core.cli.workspace_commands import workspace_command_specs
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.recovery.store import RecoveryStore
from core.runtime.store import RuntimeStore
from core.secrets.store import SecretStore
from core.workspaces.store import WorkspaceStore


def _core_command_specs(
    *,
    app_store: AppStore | None = None,
    workspace_store: WorkspaceStore | None = None,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    secret_store: SecretStore | None = None,
    recovery_store: RecoveryStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    observability_store=None,
    start_path: Path | None = None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build all core-owned CLI command specs without mixing command domains."""
    specs: list[tuple[CliCommandDefinition, Any]] = []
    specs.extend(workspace_command_specs(workspace_store=workspace_store))
    specs.extend(runtime_provider_command_specs(provider_store=provider_store, runtime_store=runtime_store))
    specs.extend(secret_command_specs(secret_store=secret_store, observability_store=observability_store))
    specs.extend(
        recovery_command_specs(
            app_store=app_store,
            runtime_store=runtime_store,
            recovery_store=recovery_store,
            provider_registry=provider_registry,
            observability_store=observability_store,
            start_path=start_path,
        )
    )
    return specs
