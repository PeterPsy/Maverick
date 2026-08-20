"""Workspace administration and actor checks for agentic profile bindings."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib

from core.observability.service import record_platform_audit, record_platform_event
from core.providers.agentic_models import (
    ActorSelectionPolicy,
    AgenticProfileDefinition,
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.agentic_profiles import publish_codex_agentic_profile
from core.providers.agentic_workspace_policy import (
    REMOTE_PREVIEW_EGRESS_POLICY_ID,
    egress_policy_for_definition,
    workspace_policy_from_patch,
)
from core.providers.builtin_certification import ensure_codex_preview_certificate
from core.providers.certificate_projection import certificate_profile_status
from core.providers.errors import (
    AgenticProfileError,
    ProviderCredentialBindingError,
    ProviderNotFoundError,
)
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.execution_binding import canonical_digest
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    feature_enabled,
)


def configure_workspace_agentic_default(
    store: ProviderStore,
    registry: ProviderRegistry,
    *,
    workspace_id: str,
    provider_id: str,
    model_id: str | None,
    model_reasoning_effort: str | None,
    observability_store=None,
    now: datetime | None = None,
) -> WorkspaceAgenticProfileBinding:
    """Serve the legacy default-provider write as one agentic control-plane update."""
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_PROFILES):
        raise AgenticProfileError("agentic_profiles_disabled")
    if provider_id != "codex":
        raise AgenticProfileError("agentic_profile_definition_must_be_published")
    timestamp = now or datetime.now(tz=UTC)
    provider = registry.get_provider_definition(provider_id)
    selected_model_id = str(model_id or provider.default_model_family or "").strip()
    model = next(
        (item for item in provider.model_options if item.model_id == selected_model_id),
        None,
    )
    if provider.model_options and model is None:
        raise AgenticProfileError("profile_model_unavailable")
    requested_reasoning = str(model_reasoning_effort or "").strip() or None
    default_reasoning = None if model is None else model.default_reasoning_effort
    if requested_reasoning is not None and requested_reasoning != default_reasoning:
        raise AgenticProfileError("agentic_reasoning_effort_is_per_session")

    profile = publish_codex_agentic_profile(
        store,
        definition=provider,
        model_id=selected_model_id,
        now=timestamp,
    )
    ensure_codex_preview_certificate(
        store,
        definition=profile,
        provider_definition=provider,
        adapter=registry.get_agentic_runtime_adapter(provider_id),
    )
    bindings = store.list_workspace_agentic_profile_bindings(workspace_id)
    existing = next(
        (
            item
            for item in bindings
            if item.definition_id == profile.definition_id
            and item.definition_revision == profile.revision
        ),
        None,
    )
    source = existing or next((item for item in bindings if item.is_default), None)
    policy = existing.workspace_policy_ceiling if existing is not None else profile.policy_ceiling
    policy_patch = {
        "max_steps_per_turn": policy.max_steps_per_turn,
        "max_tool_calls_per_turn": policy.max_tool_calls_per_turn,
        "max_wall_time_seconds": policy.max_wall_time_seconds,
        "max_output_tokens": policy.max_output_tokens,
        "max_estimated_cost_microusd": policy.max_estimated_cost_microusd,
        "allowed_remote_data_classes": list(policy.allowed_remote_data_classes),
        "tool_access_enabled": policy.tool_handle_mode != "none",
        "require_confirmation_for_mutating": policy.require_confirmation_for_mutating,
        "require_confirmation_for_destructive": policy.require_confirmation_for_destructive,
    }
    return save_workspace_agentic_binding(
        store,
        registry,
        workspace_id=workspace_id,
        definition_id=profile.definition_id,
        definition_revision=profile.revision,
        binding_id=None if existing is None else existing.binding_id,
        expected_revision=None if existing is None else existing.revision,
        credential_binding_id=None if existing is None else existing.credential_binding_id,
        enabled=True,
        is_default=True,
        actor_policy=(
            default_actor_selection_policy() if source is None else source.actor_policy
        ),
        policy_patch=policy_patch,
        confirm_fake_data_only_workspace=False,
        observability_store=observability_store,
        now=timestamp,
    )


def save_workspace_agentic_binding(
    store: ProviderStore,
    registry: ProviderRegistry,
    *,
    workspace_id: str,
    definition_id: str,
    definition_revision: str,
    credential_binding_id: str | None,
    enabled: bool,
    is_default: bool,
    actor_policy: ActorSelectionPolicy,
    policy_patch: dict[str, object],
    confirm_fake_data_only_workspace: bool,
    binding_id: str | None = None,
    expected_revision: int | None = None,
    observability_store=None,
    now: datetime | None = None,
) -> WorkspaceAgenticProfileBinding:
    """Create or update one binding while proving every policy change is restrictive."""
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_PROFILES):
        raise AgenticProfileError("agentic_profiles_disabled")
    timestamp = now or datetime.now(tz=UTC)
    definition = store.get_agentic_profile_definition(definition_id, definition_revision)
    definition_status = store.get_agentic_profile_definition_status(definition_id, definition_revision)
    if definition_status is None or definition_status.rollout_status in {"disabled", "suspended"}:
        raise AgenticProfileError("profile_definition_invalid")
    resolved_binding_id = binding_id or _workspace_binding_id(
        workspace_id,
        definition_id,
        definition_revision,
    )
    existing = next(
        (
            item
            for item in store.list_workspace_agentic_profile_bindings(workspace_id)
            if item.binding_id == resolved_binding_id
        ),
        None,
    )
    if binding_id is not None:
        try:
            binding_with_same_id = store.get_workspace_agentic_profile_binding(resolved_binding_id)
        except ProviderNotFoundError:
            binding_with_same_id = None
        if (
            binding_with_same_id is not None
            and binding_with_same_id.workspace_id != workspace_id
        ):
            raise AgenticProfileError("workspace_profile_binding_identity_conflict")
    if existing is not None and (
        existing.definition_id != definition_id
        or existing.definition_revision != definition_revision
    ):
        raise AgenticProfileError("workspace_profile_binding_identity_conflict")
    if existing is None and expected_revision is not None:
        raise AgenticProfileError("workspace_profile_binding_revision_conflict")
    if existing is not None and expected_revision != existing.revision:
        raise AgenticProfileError("workspace_profile_binding_revision_conflict")
    if is_default and not enabled:
        raise AgenticProfileError("workspace_default_profile_must_be_enabled")
    if enabled and not _actor_policy_has_principal(actor_policy):
        raise AgenticProfileError("workspace_profile_actor_policy_empty")

    model_provider = registry.get_provider_definition(definition.model_provider_id)
    normalized_credential_id = str(credential_binding_id or "").strip() or None
    if normalized_credential_id:
        credential = resolve_provider_binding(
            store,
            binding_id=normalized_credential_id,
            provider_id=definition.model_provider_id,
            workspace_id=workspace_id,
        )
        if credential is None:
            raise ProviderCredentialBindingError("credential_binding_unavailable")
    elif enabled and model_provider.requires_credentials:
        raise ProviderCredentialBindingError("credential_binding_unavailable")

    workspace_policy = workspace_policy_from_patch(
        definition.policy_ceiling,
        policy_patch,
        current_policy=None if existing is None else existing.workspace_policy_ceiling,
    )
    egress_policy_id, egress_policy_revision = egress_policy_for_definition(definition)
    if egress_policy_id == REMOTE_PREVIEW_EGRESS_POLICY_ID and enabled:
        if "workspace_internal_fake" not in workspace_policy.allowed_remote_data_classes:
            raise AgenticProfileError("fake_data_egress_class_required")
    if enabled:
        _require_active_certificate(store, registry, definition)

    revision = 0 if existing is None else existing.revision + 1
    created_at = timestamp if existing is None else existing.created_at
    desired = WorkspaceAgenticProfileBinding(
        binding_id=resolved_binding_id,
        workspace_id=workspace_id,
        definition_id=definition_id,
        definition_revision=definition_revision,
        credential_binding_id=normalized_credential_id,
        enabled=enabled,
        is_default=is_default,
        actor_policy=actor_policy,
        workspace_policy_ceiling=workspace_policy,
        egress_policy_id=egress_policy_id,
        egress_policy_revision=egress_policy_revision,
        revision=revision,
        created_at=created_at,
        updated_at=timestamp,
    )
    if existing is not None and replace(desired, revision=existing.revision, updated_at=existing.updated_at) == existing:
        return existing

    cleared_defaults: list[WorkspaceAgenticProfileBinding] = []
    try:
        if is_default:
            for other in store.list_workspace_agentic_profile_bindings(workspace_id):
                if other.binding_id == resolved_binding_id or not other.is_default:
                    continue
                cleared = replace(
                    other,
                    is_default=False,
                    revision=other.revision + 1,
                    updated_at=timestamp,
                )
                store.save_workspace_agentic_profile_binding(
                    cleared,
                    expected_revision=other.revision,
                )
                cleared_defaults.append(other)
        saved = store.save_workspace_agentic_profile_binding(
            desired,
            expected_revision=None if existing is None else existing.revision,
        )
    except Exception:
        for previous in cleared_defaults:
            current = store.get_workspace_agentic_profile_binding(previous.binding_id)
            store.save_workspace_agentic_profile_binding(
                replace(previous, revision=current.revision + 1, updated_at=timestamp),
                expected_revision=current.revision,
            )
        raise
    _audit_binding_change(
        saved,
        observability_store=observability_store,
        action="create" if existing is None else "update",
    )
    return saved


def _require_active_certificate(
    store: ProviderStore,
    registry: ProviderRegistry,
    definition: AgenticProfileDefinition,
) -> None:
    certificate = store.get_capability_certificate(definition.capability_certificate_id)
    status = store.get_capability_certificate_status(certificate.certificate_id)
    adapter = registry.get_agentic_runtime_adapter(definition.runtime_engine_id)
    effective_status = certificate_profile_status(
        certificate,
        status,
        definition=definition,
        adapter=adapter,
    )
    if effective_status != "active":
        raise AgenticProfileError(f"capability_certificate_{effective_status}")


def _actor_policy_has_principal(policy: ActorSelectionPolicy) -> bool:
    return bool(
        policy.allow_workspace_admins
        or policy.allowed_user_ids
        or policy.allowed_workspace_role_ids
    )


def _workspace_binding_id(workspace_id: str, definition_id: str, revision: str) -> str:
    digest = hashlib.sha256(
        f"{workspace_id}\0{definition_id}\0{revision}".encode("utf-8")
    ).hexdigest()[:20]
    return f"workspace-agentic-{digest}"


def _audit_binding_change(binding, *, observability_store, action: str) -> None:
    if observability_store is None:
        return
    payload = {
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "definition_id": binding.definition_id,
        "definition_revision": binding.definition_revision,
        "enabled": binding.enabled,
        "is_default": binding.is_default,
        "egress_policy_id": binding.egress_policy_id,
        "policy_digest": canonical_digest(binding.workspace_policy_ceiling),
    }
    record_platform_audit(
        observability_store,
        action=f"provider.agentic_binding.{action}",
        status="succeeded",
        source_domain="providers",
        detail=f"{action.title()}d workspace agentic binding.",
        workspace_id=binding.workspace_id,
        provider_id=None,
        payload=payload,
    )
    record_platform_event(
        observability_store,
        event_type="provider.agentic_binding.changed",
        event_plane="platform",
        source_domain="providers",
        workspace_id=binding.workspace_id,
        payload=payload,
    )
