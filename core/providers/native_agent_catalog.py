"""Model availability for certified native-runtime provider connections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.providers.errors import ProviderNotFoundError
from core.providers.native_agent_contract import NativeAgentInstallation


@dataclass(frozen=True)
class NativeAgentCatalogModel:
    """One model projected from a connected provider's authoritative catalog."""

    model_provider_id: str
    model_id: str
    model_revision: str | None
    revision_policy: Literal["exact", "provider_alias"]


def native_agent_model_provider_connected(
    installation: NativeAgentInstallation,
    *,
    model_provider_id: str,
) -> bool:
    """Return whether the certified integration connects to this provider."""
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
        try:
            catalog = registry.get_provider_definition(
                connection.catalog_provider_id
            )
        except ProviderNotFoundError:
            continue
        for option in catalog.model_options:
            identity = (connection.model_provider_id, option.model_id)
            if not option.model_id or identity in seen:
                continue
            seen.add(identity)
            models.append(
                NativeAgentCatalogModel(
                    model_provider_id=connection.model_provider_id,
                    model_id=option.model_id,
                    model_revision=None,
                    revision_policy="provider_alias",
                )
            )
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


__all__ = [
    "NativeAgentCatalogModel",
    "native_agent_catalog_models",
    "native_agent_model_available",
    "native_agent_model_provider_connected",
]
