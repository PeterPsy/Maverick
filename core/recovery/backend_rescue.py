"""Provider-backed backend rescue launch resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.providers.errors import ProviderCapabilityError
from core.providers.service import builtin_provider_registry, register_builtin_providers, resolve_provider_for_workspace
from core.providers.store import ProviderDocumentStore


@dataclass(frozen=True)
class BackendRescueCommand:
    """Resolved command for one provider-owned backend rescue attempt."""

    provider_id: str
    command: list[str]


def local_recovery_provider_store(repository_root: Path) -> ProviderDocumentStore:
    """Return the local provider store subset readable by the watchdog."""
    settings = ControlStoreSettings.from_environment(repository_root=repository_root)
    return ProviderDocumentStore(build_control_plane_collections(settings).provider)


def build_backend_rescue_command(
    *,
    repository_root: Path,
    workspace_id: str,
    codex_command: str = "codex",
    provider_command_override: str | None = None,
) -> BackendRescueCommand:
    """Resolve the configured recovery provider and ask its adapter for a rescue command."""
    store = local_recovery_provider_store(repository_root)
    registry = builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=registry, codex_command=codex_command)
    definition, selection = resolve_provider_for_workspace(
        store,
        workspace_id=workspace_id,
        registry=registry,
        codex_command=codex_command,
    )
    adapter = registry.get_runtime_adapter(definition.provider_id)
    command_builder = getattr(adapter, "build_recovery_command", None)
    if not callable(command_builder):
        raise ProviderCapabilityError(
            f"Provider `{definition.provider_id}` does not expose a backend recovery command."
        )
    command = command_builder(
        repository_root=repository_root,
        model_id=None if selection is None else selection.model_id,
        model_reasoning_effort=None if selection is None else selection.model_reasoning_effort,
        command_override=provider_command_override,
    )
    if not command:
        raise ProviderCapabilityError(
            f"Provider `{definition.provider_id}` returned an empty backend recovery command."
        )
    return BackendRescueCommand(provider_id=definition.provider_id, command=list(command))
