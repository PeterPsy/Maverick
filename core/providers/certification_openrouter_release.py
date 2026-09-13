"""Publish and activate one fully certified OpenRouter profile release."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.providers.agentic_models import default_actor_selection_policy
from core.providers.agentic_workspace_admin import save_workspace_agentic_binding
from core.providers.certificate_service import revoke_capability_certificate
from core.providers.certification_pipeline import SignedCertificationRun
from core.providers.openrouter_agentic_certification import (
    publish_openrouter_preview_certificate,
)
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_AGENTIC_PROFILE_ID,
    OPENROUTER_AGENTIC_PROFILE_REVISION,
    ensure_openrouter_agentic_preview_profile,
)


def activate_certified_openrouter_release(
    state,
    *,
    signed_run: SignedCertificationRun,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    workspace_id: str = "default",
    now: datetime | None = None,
) -> dict[str, object]:
    """Activate GLM as non-default and leave the Codex default untouched."""
    timestamp = now or datetime.now(tz=UTC)
    store = state.provider_store
    registry = state.provider_registry
    defaults_before = _workspace_defaults(store, workspace_id)
    if len(defaults_before) != 1:
        raise RuntimeError("openrouter_release_requires_one_existing_default")
    default_profile = store.get_agentic_profile_definition(
        defaults_before[0][1],
        defaults_before[0][2],
    )
    if default_profile.model_provider_id != "codex":
        raise RuntimeError("openrouter_release_requires_codex_default")
    adapter = registry.get_agentic_runtime_adapter("maverick-tool-loop")
    definition = ensure_openrouter_agentic_preview_profile(
        store,
        adapter=adapter,
        now=timestamp,
    )
    credential_bindings = [
        item
        for item in store.list_provider_bindings(
            provider_id="openrouter",
            workspace_id=workspace_id,
        )
        if item.status == "active"
    ]
    if len(credential_bindings) != 1:
        raise RuntimeError("openrouter_release_credential_binding_unavailable")
    certificate = publish_openrouter_preview_certificate(
        store,
        definition=definition,
        adapter=adapter,
        signed_run=signed_run,
        trusted_keys=trusted_keys,
    )
    existing = next(
        (
            item
            for item in store.list_workspace_agentic_profile_bindings(workspace_id)
            if item.definition_id == definition.definition_id
            and item.definition_revision == definition.revision
        ),
        None,
    )
    binding = save_workspace_agentic_binding(
        store,
        registry,
        workspace_id=workspace_id,
        definition_id=definition.definition_id,
        definition_revision=definition.revision,
        binding_id=None if existing is None else existing.binding_id,
        expected_revision=None if existing is None else existing.revision,
        credential_binding_id=credential_bindings[0].binding_id,
        enabled=True,
        is_default=False,
        actor_policy=default_actor_selection_policy(),
        policy_patch=_full_policy_patch(definition.policy_ceiling),
        observability_store=state.observability_store,
        workspace_store=state.workspace_store,
        now=timestamp,
    )
    disabled_bindings = _disable_superseded_openrouter_bindings(
        state,
        current_binding_id=binding.binding_id,
        workspace_id=workspace_id,
        now=timestamp,
    )
    revoked_certificates = _revoke_superseded_openrouter_certificates(
        state,
        current_certificate_id=certificate.certificate_id,
        now=timestamp,
    )
    defaults_after = _workspace_defaults(store, workspace_id)
    if defaults_after != defaults_before:
        raise RuntimeError("openrouter_release_changed_workspace_default")
    return {
        "provider_id": "openrouter",
        "definition_id": OPENROUTER_AGENTIC_PROFILE_ID,
        "definition_revision": OPENROUTER_AGENTIC_PROFILE_REVISION,
        "certificate_id": certificate.certificate_id,
        "binding_id": binding.binding_id,
        "binding_enabled": binding.enabled,
        "binding_is_default": binding.is_default,
        "preserved_default_binding_id": defaults_after[0][0],
        "disabled_binding_ids": disabled_bindings,
        "revoked_certificate_ids": revoked_certificates,
    }


def _workspace_defaults(store, workspace_id: str) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (
                item.binding_id,
                item.definition_id,
                item.definition_revision,
            )
            for item in store.list_workspace_agentic_profile_bindings(workspace_id)
            if item.enabled and item.is_default
        )
    )


def _full_policy_patch(policy) -> dict[str, object]:
    return {
        "max_steps_per_turn": policy.max_steps_per_turn,
        "max_tool_calls_per_turn": policy.max_tool_calls_per_turn,
        "max_wall_time_seconds": policy.max_wall_time_seconds,
        "max_output_tokens": policy.max_output_tokens,
        "max_estimated_cost_microusd": policy.max_estimated_cost_microusd,
        "allowed_remote_data_classes": list(policy.allowed_remote_data_classes),
        "tool_access_enabled": policy.tool_handle_mode != "none",
        "require_confirmation_for_mutating": (
            policy.require_confirmation_for_mutating
        ),
        "require_confirmation_for_destructive": (
            policy.require_confirmation_for_destructive
        ),
    }


def _disable_superseded_openrouter_bindings(
    state,
    *,
    current_binding_id: str,
    workspace_id: str,
    now: datetime,
) -> list[str]:
    disabled = []
    store = state.provider_store
    for binding in store.list_workspace_agentic_profile_bindings(workspace_id):
        if binding.binding_id == current_binding_id or not binding.enabled:
            continue
        definition = store.get_agentic_profile_definition(
            binding.definition_id,
            binding.definition_revision,
        )
        if definition.model_provider_id != "openrouter":
            continue
        store.save_workspace_agentic_profile_binding(
            replace(
                binding,
                enabled=False,
                is_default=False,
                revision=binding.revision + 1,
                updated_at=now,
                admission_disabled_at=now,
            ),
            expected_revision=binding.revision,
        )
        disabled.append(binding.binding_id)
    return sorted(disabled)


def _revoke_superseded_openrouter_certificates(
    state,
    *,
    current_certificate_id: str,
    now: datetime,
) -> list[str]:
    revoked = []
    store = state.provider_store
    for certificate in store.list_capability_certificates():
        if (
            certificate.certificate_id == current_certificate_id
            or certificate.model_provider_id != "openrouter"
        ):
            continue
        status = store.get_capability_certificate_status(certificate.certificate_id)
        if status is None or status.status == "revoked":
            continue
        revoke_capability_certificate(
            store,
            certificate_id=certificate.certificate_id,
            expected_revision=status.revision,
            reason="superseded_openrouter_certification",
            now=now,
            observability_store=state.observability_store,
        )
        revoked.append(certificate.certificate_id)
    return sorted(revoked)


__all__ = ["activate_certified_openrouter_release"]
