"""Workspace-aware provider selection services."""

from __future__ import annotations

from datetime import UTC, datetime

from core.providers.errors import (
    ProviderCapabilityError,
    ProviderCredentialBindingError,
    ProviderDisabledError,
    ProviderSelectionError,
)
from core.providers.models import ProviderDefinition, ProviderSelection
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


class ProviderSelectionService:
    """Resolve and persist provider selection for workspace runtime use."""

    def __init__(self, store: ProviderStore, registry: ProviderRegistry) -> None:
        self.store = store
        self.registry = registry

    def configure_workspace_provider(
        self,
        *,
        workspace_id: str,
        provider_id: str,
        binding_id: str | None = None,
        selection_reason: str = "configured by control-plane policy",
        now: datetime | None = None,
    ) -> ProviderSelection:
        """Persist one workspace-scoped provider selection."""
        definition = self.registry.get_provider_definition(provider_id)
        self._validate_runtime_backend_candidate(definition)
        binding = resolve_provider_binding(
            self.store,
            provider_id=provider_id,
            workspace_id=workspace_id,
            binding_id=binding_id,
        )
        if definition.requires_credentials and binding is None:
            raise ProviderCredentialBindingError(
                f"Provider `{provider_id}` requires a credential binding before it can be selected."
            )
        timestamp = now or utcnow()
        selection = ProviderSelection(
            selection_id=f"{workspace_id}:{provider_id}",
            workspace_id=workspace_id,
            provider_id=provider_id,
            binding_id=binding.binding_id if binding is not None else None,
            selection_scope="workspace_default",
            selection_reason=selection_reason,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return self.store.save_provider_selection(selection)

    def get_workspace_provider_selection(self, workspace_id: str) -> ProviderSelection | None:
        """Return the persisted workspace provider selection, if any."""
        return self.store.get_provider_selection(workspace_id)

    def resolve_runtime_backend_provider(
        self,
        *,
        workspace_id: str,
        require_tools: bool = True,
    ) -> tuple[ProviderDefinition, ProviderSelection | None]:
        """Resolve the effective runtime backend provider for one workspace."""
        selection = self.store.get_provider_selection(workspace_id)
        if selection is not None:
            definition = self.registry.get_provider_definition(selection.provider_id)
            self._validate_runtime_backend_candidate(definition)
            if require_tools and not definition.capabilities.supports_tools:
                raise ProviderCapabilityError(f"Provider `{definition.provider_id}` does not support runtime tool use.")
            if definition.requires_credentials:
                binding = resolve_provider_binding(
                    self.store,
                    provider_id=definition.provider_id,
                    workspace_id=workspace_id,
                    binding_id=selection.binding_id,
                )
                if binding is None:
                    raise ProviderCredentialBindingError(
                        f"Provider `{definition.provider_id}` is selected but has no active credential binding."
                    )
            return definition, selection

        candidates = [
            definition
            for definition in self.registry.list_provider_definitions()
            if definition.kind == "runtime_backend" and definition.status == "active"
        ]
        if require_tools:
            candidates = [definition for definition in candidates if definition.capabilities.supports_tools]
        if not candidates:
            raise ProviderSelectionError("No active runtime backend provider is available.")
        return candidates[0], None

    def _validate_runtime_backend_candidate(self, definition: ProviderDefinition) -> None:
        if definition.status != "active":
            raise ProviderDisabledError(f"Provider `{definition.provider_id}` is disabled.")
        if definition.kind != "runtime_backend":
            raise ProviderCapabilityError(
                f"Provider `{definition.provider_id}` is not a runtime backend and cannot own runtime execution."
            )
        if not definition.capabilities.supports_interactive_runtime:
            raise ProviderCapabilityError(
                f"Provider `{definition.provider_id}` does not support interactive runtime execution."
            )
