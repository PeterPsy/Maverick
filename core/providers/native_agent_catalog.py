"""Model availability for certified native-runtime provider connections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from typing import Literal

from core.providers.errors import ProviderNotFoundError
from core.providers.native_agent_contract import NativeAgentInstallation
from core.providers.models import ProviderModelOption
from core.runtime.execution_binding import canonical_digest


@dataclass(frozen=True)
class NativeAgentCatalogModel:
    """One model projected from a connected provider's authoritative catalog."""

    model_provider_id: str
    model_id: str
    model_revision: str | None
    revision_policy: Literal["exact", "provider_alias"]
    reasoning_efforts: tuple[str, ...] = ()
    default_reasoning_effort: str | None = None

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True)
class NativeAgentCatalogSnapshot:
    """Successful trusted-runtime observation; persisted UI metadata is not one."""

    runtime_engine_id: str
    model_provider_id: str
    catalog_provider_id: str
    source_id: str
    observed_at: datetime
    expires_at: datetime
    models: tuple[NativeAgentCatalogModel, ...]
    model_options: tuple[ProviderModelOption, ...]

    @property
    def digest(self) -> str:
        return canonical_digest((self.source_id, self.models))


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
        catalog = registry.get_native_agent_catalog(
            installation.manifest.runtime_engine_id, connection.model_provider_id
        )
        if catalog is None or (
            catalog.runtime_engine_id != installation.manifest.runtime_engine_id
            or catalog.catalog_provider_id != connection.catalog_provider_id
            or catalog.model_provider_id != connection.model_provider_id
            or datetime.now(tz=UTC) >= catalog.expires_at
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


def require_native_agent_model_available(registry, definition, *, certificate=None) -> None:
    """Fence model/revision/reasoning availability at every admission boundary."""
    from core.providers.errors import AgenticProfileError
    from core.providers.execution_families import effective_agentic_execution_family

    if effective_agentic_execution_family(
        getattr(definition, "execution_family", ""),
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=definition.adapter_id,
        model_provider_id=definition.model_provider_id,
        provider_protocol=definition.provider_protocol,
    ) != "native_agent":
        return
    try:
        installation = registry.get_native_agent_installation(definition.runtime_engine_id)
    except ProviderNotFoundError as error:
        raise AgenticProfileError("native_agent_installation_missing") from error
    model = next((model for model in native_agent_catalog_models(registry, installation)
                  if model.model_provider_id == definition.model_provider_id
                  and model.model_id == definition.model_id), None)
    if model is None:
        raise AgenticProfileError("native_agent_model_unavailable")
    if (
        model.model_revision != definition.model_revision
        or model.revision_policy != definition.model_revision_policy
        or (definition.native_model_catalog_digest and definition.native_model_catalog_digest != model.digest)
        or (certificate is not None and (
            certificate.certified_reasoning_efforts != model.reasoning_efforts
            or certificate.default_reasoning_effort != model.default_reasoning_effort
        ))
    ):
        raise AgenticProfileError("native_agent_model_catalog_mismatch")


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
    "require_native_agent_model_available",
]
