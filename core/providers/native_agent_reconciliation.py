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
from core.providers.errors import (
    CapabilityCertificateError,
    ProviderNotFoundError,
)
from core.providers.native_agent_certificates import validate_native_connection_certificate
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


def refresh_antigravity_native_catalog(
    registry: ProviderRegistry,
    *,
    store: ProviderStore | None = None,
    force: bool = False,
) -> bool:
    """Publish catalog metadata and certified projections without auto-activation."""
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
    from core.providers.native_agent_certificates import (
        native_connection_reference,
    )

    try:
        certificate = store.get_capability_certificate(
            native_connection_reference(controller.installation, "google")
        )
        validate_native_connection_certificate(
            store,
            certificate,
            installation=controller.installation,
        )
    except (ProviderNotFoundError, CapabilityCertificateError):
        return False
    return True


def _reconcile_antigravity_native_models(store, controller, snapshot) -> None:
    """Project slugs from one still-valid connection without renewing evidence."""
    from core.providers.antigravity_agentic_certification import (
        publish_antigravity_model_certificate,
    )
    from core.providers.antigravity_agentic_profile import (
        publish_antigravity_agentic_profile,
    )

    current_profiles: set[tuple[str, str]] = set()
    for model in snapshot.models:
        profile = publish_antigravity_agentic_profile(
            store,
            installation=controller.installation,
            model=model,
            now=snapshot.observed_at,
        )
        current_profiles.add((profile.definition_id, profile.revision))
        publish_antigravity_model_certificate(
            store,
            profile=profile,
            adapter=controller,
            now=snapshot.observed_at,
        )
    current_definition_ids = {
        definition_id for definition_id, _revision in current_profiles
    }
    for profile in store.list_agentic_profile_definitions():
        identity = (profile.definition_id, profile.revision)
        if (
            profile.runtime_engine_id != "antigravity-cli"
            or identity in current_profiles
            or profile.definition_id not in current_definition_ids
        ):
            continue
        status = store.get_agentic_profile_definition_status(*identity)
        if status is None or status.rollout_status in {"disabled", "suspended"}:
            continue
        store.save_agentic_profile_definition_status(
            replace(
                status,
                rollout_status="suspended",
                revision=status.revision + 1,
                updated_at=snapshot.observed_at,
            ),
            expected_revision=status.revision,
        )


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


__all__ = [
    "refresh_antigravity_native_catalog",
    "refresh_codex_native_catalog",
    "reconcile_codex_native_models",
]
