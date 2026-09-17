"""Direct workspace configuration for agentic provider/model choices."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib

from core.observability.service import record_platform_audit, record_platform_event
from core.providers.agentic_models import (
    ActorSelectionPolicy,
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.agentic_profiles import publish_codex_agentic_profile
from core.providers.agentic_workspace_policy import (
    egress_policy_for_definition,
    workspace_policy_from_patch,
)
from core.providers.errors import (
    AgenticProfileError,
    ProviderCredentialBindingError,
    ProviderNotFoundError,
)
from core.providers.models import ProviderSelection
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.store import ProviderStore
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    feature_enabled,
)
from core.runtime.remote_agentic_admission import require_remote_agentic_session_admission


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
    """Select a Codex provider/model directly for a workspace."""
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
    supported_efforts = {
        item.effort for item in (() if model is None else model.supported_reasoning_efforts)
    }
    if requested_reasoning is not None and requested_reasoning not in supported_efforts:
        raise AgenticProfileError("profile_reasoning_effort_unsupported")
    profile = publish_codex_agentic_profile(
        store,
        definition=provider,
        model_id=selected_model_id,
        now=timestamp,
    )
    existing = next(
        (
            item
            for item in store.list_workspace_agentic_profile_bindings(workspace_id)
            if item.definition_id == profile.definition_id
        ),
        None,
    )
    source = existing or next(
        (
            item
            for item in store.list_workspace_agentic_profile_bindings(workspace_id)
            if item.is_default
        ),
        None,
    )
    policy = existing.workspace_policy_ceiling if existing else profile.policy_ceiling
    saved = save_workspace_agentic_binding(
        store,
        registry,
        workspace_id=workspace_id,
        definition_id=profile.definition_id,
        binding_id=None if existing is None else existing.binding_id,
        credential_binding_id=None if existing is None else existing.credential_binding_id,
        enabled=True,
        is_default=True,
        actor_policy=(
            default_actor_selection_policy() if source is None else source.actor_policy
        ),
        policy_patch=_policy_patch(policy),
        observability_store=observability_store,
        now=timestamp,
    )
    selection = store.get_provider_selection(workspace_id)
    store.save_provider_selection(
        ProviderSelection(
            selection_id=f"workspace:{workspace_id}:{provider_id}",
            workspace_id=workspace_id,
            provider_id=provider_id,
            binding_id=saved.credential_binding_id,
            selection_scope="workspace_default",
            selection_reason="workspace agentic default selection",
            created_at=timestamp if selection is None else selection.created_at,
            updated_at=timestamp,
            model_id=selected_model_id,
            model_reasoning_effort=None,
        )
    )
    return saved


def save_workspace_agentic_binding(
    store: ProviderStore,
    registry: ProviderRegistry,
    *,
    workspace_id: str,
    definition_id: str,
    credential_binding_id: str | None,
    enabled: bool,
    is_default: bool,
    actor_policy: ActorSelectionPolicy,
    policy_patch: dict[str, object],
    binding_id: str | None = None,
    observability_store=None,
    now: datetime | None = None,
    workspace_store: object | None = None,
) -> WorkspaceAgenticProfileBinding:
    """Create or replace one direct workspace provider/model configuration."""
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_PROFILES):
        raise AgenticProfileError("agentic_profiles_disabled")
    timestamp = now or datetime.now(tz=UTC)
    definition = store.get_agentic_profile_definition(definition_id)
    resolved_binding_id = binding_id or _workspace_binding_id(workspace_id, definition_id)
    try:
        existing = store.get_workspace_agentic_profile_binding(resolved_binding_id)
    except ProviderNotFoundError:
        existing = None
    if existing is not None and existing.workspace_id != workspace_id:
        raise AgenticProfileError("workspace_profile_binding_identity_conflict")
    if is_default and not enabled:
        raise AgenticProfileError("workspace_default_profile_must_be_enabled")
    if enabled and not _actor_policy_has_principal(actor_policy):
        raise AgenticProfileError("workspace_profile_actor_policy_empty")
    if enabled:
        require_remote_agentic_session_admission(
            definition,
            workspace_id=workspace_id,
            workspace_store=workspace_store,
        )
    try:
        model_provider = registry.get_provider_definition(definition.model_provider_id)
    except ProviderNotFoundError:
        model_provider = registry.get_provider_definition(definition.runtime_engine_id)
    normalized_credential_id = str(credential_binding_id or "").strip() or None
    if normalized_credential_id and resolve_provider_binding(
        store,
        binding_id=normalized_credential_id,
        provider_id=definition.model_provider_id,
        workspace_id=workspace_id,
    ) is None:
        raise ProviderCredentialBindingError("credential_binding_unavailable")
    if enabled and model_provider.requires_credentials and not normalized_credential_id:
        raise ProviderCredentialBindingError("credential_binding_unavailable")
    workspace_policy = workspace_policy_from_patch(
        definition.policy_ceiling,
        policy_patch,
        current_policy=None if existing is None else existing.workspace_policy_ceiling,
    )
    egress_policy_id, egress_policy_revision = egress_policy_for_definition(definition)
    saved = WorkspaceAgenticProfileBinding(
        binding_id=resolved_binding_id,
        workspace_id=workspace_id,
        definition_id=definition_id,
        credential_binding_id=normalized_credential_id,
        enabled=enabled,
        is_default=is_default,
        actor_policy=actor_policy,
        workspace_policy_ceiling=workspace_policy,
        egress_policy_id=egress_policy_id,
        egress_policy_revision=egress_policy_revision,
        created_at=timestamp if existing is None else existing.created_at,
        updated_at=timestamp,
    )
    if is_default:
        for other in store.list_workspace_agentic_profile_bindings(workspace_id):
            if other.binding_id != resolved_binding_id and other.is_default:
                store.save_workspace_agentic_profile_binding(
                    replace(other, is_default=False, updated_at=timestamp)
                )
    store.save_workspace_agentic_profile_binding(saved)
    _audit_binding_change(
        saved,
        observability_store=observability_store,
        action="create" if existing is None else "update",
    )
    return saved


def _policy_patch(policy) -> dict[str, object]:
    return {
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


def _actor_policy_has_principal(policy: ActorSelectionPolicy) -> bool:
    return bool(
        policy.allow_workspace_admins
        or policy.allowed_user_ids
        or policy.allowed_workspace_role_ids
    )


def _workspace_binding_id(workspace_id: str, definition_id: str) -> str:
    digest = hashlib.sha256(
        f"{workspace_id}\0{definition_id}".encode("utf-8")
    ).hexdigest()[:20]
    return f"workspace-agentic-{digest}"


def _audit_binding_change(binding, *, observability_store, action: str) -> None:
    if observability_store is None:
        return
    payload = {
        "binding_id": binding.binding_id,
        "definition_id": binding.definition_id,
        "enabled": binding.enabled,
        "is_default": binding.is_default,
        "egress_policy_id": binding.egress_policy_id,
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
