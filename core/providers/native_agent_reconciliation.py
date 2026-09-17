"""Refresh native model discovery and current direct model configs."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.providers.agentic_profiles import publish_codex_agentic_profile
from core.providers.errors import ProviderNotFoundError
from core.providers.native_agent_discovery import (
    discover_antigravity_native_catalog,
    discover_codex_native_catalog,
)

if TYPE_CHECKING:
    from core.providers.models import ProviderDefinition
    from core.providers.provider_registry import ProviderRegistry
    from core.providers.store import ProviderStore


def refresh_codex_native_catalog(
    registry: ProviderRegistry,
    *,
    store: ProviderStore | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> bool:
    """Refresh discovery; a failed refresh keeps the last usable snapshot."""
    with registry.native_catalog_lock:
        snapshot = discover_codex_native_catalog(
            registry.get_runtime_adapter("codex"), force=force,
        )
        if snapshot is None:
            return False
        definition = registry.get_provider_definition("codex")
        ids = {model.model_id for model in snapshot.models}
        default = definition.default_model_family
        if default not in ids and ids:
            default = "gpt-5.6-sol" if "gpt-5.6-sol" in ids else snapshot.models[0].model_id
        definition = replace(
            definition, model_options=list(snapshot.model_options), default_model_family=default,
        )
        registry.publish_native_agent_catalog(snapshot)
        registry.register_provider_definition(definition)
        if store is None:
            return True
        key = (id(store), snapshot.source_id, snapshot.models)
        if registry._native_catalog_reconciliations.get(("codex", "codex")) == key:
            return True
        try:
            reconcile_codex_native_models(store, registry, definition, now=now)
            store.save_provider_definition(definition)
        except Exception:
            raise
        registry._native_catalog_reconciliations[("codex", "codex")] = key
        return True


def refresh_antigravity_native_catalog(
    registry: ProviderRegistry,
    *,
    store: ProviderStore | None = None,
    force: bool = False,
) -> bool:
    """Publish catalog metadata and profile projections without auto-activation."""
    with registry.native_catalog_lock:
        controller = registry.get_native_agent_controller("antigravity-cli")
        snapshot = discover_antigravity_native_catalog(
            controller.engine_adapter,
            force=force,
        )
        if snapshot is None:
            registry.revoke_native_agent_activation("antigravity-cli")
            registry.clear_native_agent_catalog("antigravity-cli", "google")
            timestamp = datetime.now(tz=UTC)
            definition = registry.get_provider_definition("antigravity-cli")
            registry.register_provider_definition(
                replace(definition, status="disabled", updated_at=timestamp)
            )
            if store is not None:
                try:
                    persisted = store.get_provider_definition(
                        "antigravity-cli"
                    )
                except ProviderNotFoundError:
                    pass
                else:
                    if persisted.status != "disabled":
                        store.save_provider_definition(
                            replace(
                                persisted,
                                status="disabled",
                                updated_at=timestamp,
                            )
                        )
            return False
        definition = registry.get_provider_definition("antigravity-cli")
        model_ids = {model.model_id for model in snapshot.models}
        default = definition.default_model_family
        if default not in model_ids:
            default = (
                "gemini-3.6-flash-high"
                if "gemini-3.6-flash-high" in model_ids
                else snapshot.models[0].model_id
            )
        existing = None
        if store is not None:
            try:
                existing = store.get_provider_definition("antigravity-cli")
            except ProviderNotFoundError:
                pass
        connection_ready = _antigravity_connection_ready(
            store,
            controller,
        )
        connection_active = bool(
            connection_ready
            and existing is not None
            and existing.status == "active"
        )
        if connection_active:
            registry.authorize_native_agent_activation("antigravity-cli")
        else:
            registry.revoke_native_agent_activation("antigravity-cli")
        definition = replace(
            definition,
            status="active" if connection_active else "disabled",
            default_model_family=default,
            model_options=list(snapshot.model_options),
            updated_at=snapshot.observed_at,
        )
        registry.publish_native_agent_catalog(snapshot)
        if store is not None:
            if existing is not None:
                definition = replace(
                    definition,
                    created_at=existing.created_at,
                )
            try:
                if connection_ready:
                    _reconcile_antigravity_native_models(
                        store,
                        controller,
                        snapshot,
                    )
                store.save_provider_definition(definition)
            except Exception:
                registry.revoke_native_agent_activation("antigravity-cli")
                registry.clear_native_agent_catalog(
                    "antigravity-cli",
                    "google",
                )
                registry.register_provider_definition(
                    replace(definition, status="disabled")
                )
                raise
        registry.register_provider_definition(definition)
        return True


def _antigravity_connection_ready(store, controller) -> bool:
    if store is None:
        return False
    try:
        status = controller.installation.inspector.inspect()
    except Exception:
        return False
    return status.availability == "installed" and status.health in {
        "healthy",
        "degraded",
    }


def _reconcile_antigravity_native_models(store, controller, snapshot) -> None:
    """Project slugs from the native runtime's current catalog."""
    from core.providers.antigravity_agentic_profile import (
        publish_antigravity_agentic_profile,
    )

    for model in snapshot.models:
        publish_antigravity_agentic_profile(
            store,
            installation=controller.installation,
            model=model,
            now=snapshot.observed_at,
        )


def reconcile_codex_native_models(
    store: ProviderStore,
    registry: ProviderRegistry,
    definition: ProviderDefinition,
    *,
    now: datetime | None = None,
) -> None:
    """Publish profiles for every model in the current Codex catalog."""
    timestamp = now or datetime.now(tz=UTC)
    for model in definition.model_options:
        publish_codex_agentic_profile(
            store, definition=definition, model_id=model.model_id, now=timestamp,
        )


__all__ = [
    "refresh_antigravity_native_catalog",
    "refresh_codex_native_catalog",
    "reconcile_codex_native_models",
]
