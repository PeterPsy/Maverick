"""Atomic live-catalog publication after immutable model projections are ready."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.providers.agentic_profiles import publish_codex_agentic_profile
from core.providers.builtin_certification import (
    ensure_codex_connection_certificate,
    ensure_codex_preview_certificate,
)
from core.providers.errors import CapabilityCertificateError
from core.providers.native_agent_certificates import validate_native_connection_certificate
from core.providers.native_agent_discovery import discover_codex_native_catalog

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
    """Commit catalog + eligible projections together, or expose no authority.

    The lock fences catalog readers/admission while persistent immutable records
    are staged. On any write failure their catalog gate stays closed, including
    across restart (only fresh discovery can republish the gate).
    """
    with registry.native_catalog_lock:
        snapshot = discover_codex_native_catalog(
            registry.get_runtime_adapter("codex"), force=force,
        )
        if snapshot is None:
            registry.clear_native_agent_catalog("codex", "codex")
            if store is not None:
                _adopt_existing_codex_connection(store, registry)
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
        key = (id(store), snapshot.digest)
        if registry._native_catalog_reconciliations.get(("codex", "codex")) == key:
            return True
        try:
            _adopt_existing_codex_connection(store, registry)
            reconcile_codex_native_models(store, registry, definition, now=now)
            store.save_provider_definition(definition)
        except Exception:
            registry.clear_native_agent_catalog("codex", "codex")
            raise
        registry._native_catalog_reconciliations[("codex", "codex")] = key
        return True


def _adopt_existing_codex_connection(store: ProviderStore, registry: ProviderRegistry) -> None:
    # Empty or failed discovery fences new admission, not an existing pinned
    # connection. Adopt old authority independently of currently visible slugs.
    legacy = next(
        (item for item in store.list_agentic_profile_definitions()
         if item.runtime_engine_id == "codex"),
        None,
    )
    if legacy is not None:
        ensure_codex_connection_certificate(
            store, definition=legacy, adapter=registry.get_agentic_runtime_adapter("codex"),
        )


def reconcile_codex_native_models(
    store: ProviderStore,
    registry: ProviderRegistry,
    definition: ProviderDefinition,
    *,
    now: datetime | None = None,
) -> None:
    """Never mint a certification run/expiry or reset revocation for a new slug."""
    timestamp = now or datetime.now(tz=UTC)
    adapter = registry.get_agentic_runtime_adapter("codex")
    for model in definition.model_options:
        profile = publish_codex_agentic_profile(
            store, definition=definition, model_id=model.model_id, now=timestamp,
        )
        connection = ensure_codex_connection_certificate(store, definition=profile, adapter=adapter)
        try:
            validate_native_connection_certificate(
                store, connection, now=timestamp, installation=adapter.installation,
            )
        except CapabilityCertificateError:
            # Revoked/expired installations still boot, but cannot publish new
            # active projections or enabled bindings.
            continue
        try:
            ensure_codex_preview_certificate(
                store, definition=profile, provider_definition=definition,
                adapter=adapter, now=timestamp,
            )
        except CapabilityCertificateError as error:
            if error.reason_code != "profile_revision_artifact_mismatch":
                raise
            # An already-corrupt immutable model projection is unavailable,
            # not replaceable; it must not prevent unrelated host startup.
    from core.providers.agentic_migration import _roll_forward_enabled_codex_bindings

    _roll_forward_enabled_codex_bindings(
        store, registry,
        workspace_ids={
            item.workspace_id for item in store.list_all_workspace_agentic_profile_bindings()
        },
        now=timestamp,
    )


__all__ = ["refresh_codex_native_catalog", "reconcile_codex_native_models"]
