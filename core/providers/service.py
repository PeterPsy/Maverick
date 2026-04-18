"""Provider-domain service facade and builtin provider bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime

from core.providers.models import ProviderDefinition, ProviderSelection, RuntimeBackendLaunchSpec
from core.providers.provider_codex import CodexProviderAdapter
from core.providers.provider_credentials import bind_provider_credential, disable_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.provider_selection import ProviderSelectionService
from core.providers.store import ProviderStore
from core.runtime.runtime_session import RuntimeSessionRecord


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def builtin_provider_registry(*, codex_command: str = "codex") -> ProviderRegistry:
    """Build the builtin provider registry shipped by the core."""
    registry = ProviderRegistry()
    registry.register_runtime_adapter(CodexProviderAdapter(codex_command=codex_command))
    return registry


def register_builtin_providers(
    store: ProviderStore,
    *,
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
) -> list[ProviderDefinition]:
    """Persist builtin provider definitions into the provider store."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    definitions = active_registry.list_provider_definitions()
    for definition in definitions:
        store.save_provider_definition(definition)
    return definitions


def list_available_providers(
    store: ProviderStore,
    *,
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
) -> list[ProviderDefinition]:
    """List provider definitions from the authoritative registry."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    return active_registry.list_provider_definitions()


def configure_workspace_provider(
    store: ProviderStore,
    *,
    workspace_id: str,
    provider_id: str,
    binding_id: str | None = None,
    selection_reason: str = "configured by control-plane policy",
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
    now: datetime | None = None,
) -> ProviderSelection:
    """Persist the selected runtime provider for one workspace."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    service = ProviderSelectionService(store, active_registry)
    return service.configure_workspace_provider(
        workspace_id=workspace_id,
        provider_id=provider_id,
        binding_id=binding_id,
        selection_reason=selection_reason,
        now=now,
    )


def resolve_provider_for_runtime_session(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
) -> tuple[ProviderDefinition, ProviderSelection | None]:
    """Resolve the effective provider selection for one runtime session."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    service = ProviderSelectionService(store, active_registry)
    return service.resolve_runtime_backend_provider(workspace_id=session.workspace_id)


def build_runtime_backend_launch_spec(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    registry: ProviderRegistry | None = None,
    codex_command: str = "codex",
) -> RuntimeBackendLaunchSpec:
    """Build the launch spec for the selected provider for one runtime session."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    definition, _selection = resolve_provider_for_runtime_session(
        store,
        session=session,
        registry=active_registry,
        codex_command=codex_command,
    )
    adapter = active_registry.get_runtime_adapter(definition.provider_id)
    return adapter.build_launch_spec(session)


__all__ = [
    "bind_provider_credential",
    "builtin_provider_registry",
    "build_runtime_backend_launch_spec",
    "configure_workspace_provider",
    "disable_provider_binding",
    "list_available_providers",
    "register_builtin_providers",
    "resolve_provider_for_runtime_session",
    "utcnow",
]
