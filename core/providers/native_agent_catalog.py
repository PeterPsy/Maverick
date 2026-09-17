"""Model availability for native-runtime provider connections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Literal

from core.providers.native_agent_contract import NativeAgentInstallation
from core.providers.models import ProviderModelOption


@dataclass(frozen=True)
class NativeAgentCatalogModel:
    """One model projected from a connected provider's authoritative catalog."""

    model_provider_id: str
    model_id: str
    model_revision: str | None
    revision_policy: Literal["exact", "provider_alias"]
    reasoning_efforts: tuple[str, ...] = ()
    default_reasoning_effort: str | None = None

@dataclass(frozen=True)
class NativeAgentCatalogSnapshot:
    """Successful trusted-runtime observation; persisted UI metadata is not one."""

    runtime_engine_id: str
    model_provider_id: str
    catalog_provider_id: str
    source_id: str
    observed_at: datetime
    models: tuple[NativeAgentCatalogModel, ...]
    model_options: tuple[ProviderModelOption, ...]

def native_agent_model_provider_connected(
    installation: NativeAgentInstallation,
    *,
    model_provider_id: str,
) -> bool:
    """Return whether the integration connects to this provider."""
    return any(
        connection.model_provider_id == model_provider_id
        for connection in installation.model_provider_connections
    )


def native_agent_catalog_models(
    registry,
    installation: NativeAgentInstallation,
) -> tuple[NativeAgentCatalogModel, ...]:
    """Project selectable models from each connection's current catalog."""
    models: list[NativeAgentCatalogModel] = []
    seen: set[tuple[str, str]] = set()
    for connection in installation.model_provider_connections:
        catalog = registry.get_native_agent_catalog(
            installation.manifest.runtime_engine_id, connection.model_provider_id
        )
        if catalog is None or (
            catalog.runtime_engine_id != installation.manifest.runtime_engine_id
            or catalog.catalog_provider_id != connection.catalog_provider_id
            or catalog.model_provider_id != connection.model_provider_id
        ):
            continue
        for model in catalog.models:
            identity = (connection.model_provider_id, model.model_id)
            if model.model_provider_id != connection.model_provider_id:
                continue
            if not model.model_id or identity in seen:
                continue
            seen.add(identity)
            models.append(model)
    return tuple(models)


def native_agent_model_available(
    registry,
    installation: NativeAgentInstallation,
    *,
    model_provider_id: str,
    model_id: str,
) -> bool:
    """Return whether a connected native runtime currently advertises a model."""
    return any(
        model.model_provider_id == model_provider_id and model.model_id == model_id
        for model in native_agent_catalog_models(registry, installation)
    )


def native_catalog_admission(operation):
    """Serialize admission writes with publication of an entire catalog epoch."""
    @wraps(operation)
    def guarded(store, registry, *args, **kwargs):
        with registry.native_catalog_lock:
            return operation(store, registry, *args, **kwargs)
    return guarded


__all__ = [
    "NativeAgentCatalogModel",
    "NativeAgentCatalogSnapshot",
    "native_catalog_admission",
    "native_agent_catalog_models",
    "native_agent_model_available",
    "native_agent_model_provider_connected",
]
