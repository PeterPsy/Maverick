"""Provider registry and runtime adapter contracts."""

from __future__ import annotations

from typing import Protocol

from core.providers.errors import ProviderNotFoundError
from core.providers.models import ProviderDefinition, RuntimeBackendLaunchSpec
from core.runtime.runtime_session import RuntimeSessionRecord


class RuntimeBackendAdapter(Protocol):
    """Contract implemented by concrete runtime backend adapters."""

    def provider_definition(self) -> ProviderDefinition:
        ...

    def validate_backend(self) -> None:
        ...

    def build_launch_spec(self, session: RuntimeSessionRecord) -> RuntimeBackendLaunchSpec:
        ...


class ProviderRegistry:
    """In-memory registry for provider definitions and runtime adapters."""

    def __init__(self) -> None:
        self._definitions: dict[str, ProviderDefinition] = {}
        self._runtime_adapters: dict[str, RuntimeBackendAdapter] = {}

    def register_provider_definition(self, definition: ProviderDefinition) -> ProviderDefinition:
        """Register one provider definition without a runtime adapter."""
        self._definitions[definition.provider_id] = definition
        return definition

    def register_runtime_adapter(self, adapter: RuntimeBackendAdapter) -> ProviderDefinition:
        """Register one runtime backend adapter and its canonical definition."""
        definition = adapter.provider_definition()
        self._definitions[definition.provider_id] = definition
        self._runtime_adapters[definition.provider_id] = adapter
        return definition

    def list_provider_definitions(self) -> list[ProviderDefinition]:
        """Return all known provider definitions."""
        return [self._definitions[provider_id] for provider_id in sorted(self._definitions)]

    def get_provider_definition(self, provider_id: str) -> ProviderDefinition:
        """Return one provider definition by canonical id."""
        if provider_id not in self._definitions:
            raise ProviderNotFoundError(f"Provider `{provider_id}` is not registered.")
        return self._definitions[provider_id]

    def get_runtime_adapter(self, provider_id: str) -> RuntimeBackendAdapter:
        """Return the runtime backend adapter for one provider."""
        if provider_id not in self._runtime_adapters:
            raise ProviderNotFoundError(f"Runtime backend adapter `{provider_id}` is not registered.")
        return self._runtime_adapters[provider_id]

