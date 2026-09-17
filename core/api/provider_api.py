"""Provider and runtime-status HTTP API for the hosted platform shell."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from core.api.http import StartResponse, json_response, query_params
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_provider_selection_authority
from core.providers.models import ProviderDefinition, ProviderHostedSelection, ProviderSelection, ProviderSpeechSelection
from core.providers.errors import (
    AgenticRuntimeError,
    ProviderError,
    ProviderNotFoundError,
)
from core.providers.agentic_adapter import RuntimeHealthContext
from core.providers.agentic_models import ActorSelectionPolicy
from core.providers.agentic_workspace_admin import (
    configure_workspace_agentic_default,
    save_workspace_agentic_binding,
)
from core.providers.agentic_workspace_policy import human_actor_selection_allowed
from core.providers.agentic_data_policies import (
    remote_data_policy_requires_fake_data_attestation,
)
from core.providers.execution_families import (
    NATIVE_AGENT_EXECUTION_FAMILY,
    NO_WORKSPACE_ACTIONS_MESSAGE,
    execution_family_catalog,
)
from core.providers.execution_family_migration import (
    execution_family_selection_migration_payload,
)
from core.providers.execution_family_readiness import (
    inspect_agentic_family_readiness,
)
from core.providers.hosted_text_profiles import build_hosted_text_profile
from core.providers.native_agent_status import native_agent_status_items
from core.providers.payloads import (
    hosted_provider_selection_payload,
    provider_model_option_payload,
    provider_payload,
    provider_selection_payload,
    provider_subscription_usage_payload,
    routing_decision_payload,
    sort_provider_definitions,
    speech_provider_selection_payload,
)
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.read_snapshot import ProviderReadSnapshot
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import (
    activate_hosted_model_provider,
    activate_speech_provider,
    configure_hosted_model_provider,
    configure_speech_provider,
    effective_provider_registry,
    read_workspace_provider_subscription_usage,
    resolve_workspace_provider_status,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.execution_binding import (
    build_runtime_execution_binding,
    canonical_digest,
)
from core.runtime.async_runtime import run_runtime_coroutine
from core.runtime.authority import (
    blocked_runtime_capability_payload,
    runtime_capability_payload,
    intersect_runtime_policies,
    resolve_runtime_authority,
)
from core.runtime.authority_service import resolve_runtime_authority_snapshot
from core.runtime.hosted_agentic_policy import authorized_core_tool_handles
from core.runtime.remote_agentic_admission import remote_agentic_containment_reason
from core.runtime.research_runtime import research_runtime_kind
from core.runtime.routing import resolve_runtime_execution_mode
from core.runtime.public_status import public_runtime_recovery_reason_code
from core.usage.quota import record_provider_quota_snapshots
from core.workspaces.data_governance import attestation_safe_projection


@dataclass
class ProviderProjectionContext:
    """Coherent request-local inputs for provider and runtime projections."""

    provider_store: ProviderReadSnapshot
    registry: ProviderRegistry
    _native_items: list[dict[str, object]] | None = None

    def native_items(self) -> list[dict[str, object]]:
        if self._native_items is None:
            self._native_items = native_agent_status_items(
                self.registry,
                store=self.provider_store,
            )
        return self._native_items


def provider_projection_context(
    state: PlatformState,
    *,
    refresh_model_catalog: bool = False,
) -> ProviderProjectionContext:
    """Capture one registry and provider read snapshot for a bulk projection."""
    registry = getattr(state, "provider_registry", None)
    if registry is None or refresh_model_catalog:
        registry = effective_provider_registry(
            state.provider_store,
            registry=registry,
            refresh_model_catalog=refresh_model_catalog,
        )
    return ProviderProjectionContext(
        provider_store=ProviderReadSnapshot(state.provider_store),
        registry=registry,
    )


def provider_model_settings_payload(definition: ProviderDefinition, selection: ProviderSelection | None) -> dict[str, object]:
    """Return effective workspace model settings for a provider."""
    selected_model_id = (None if selection is None else selection.model_id) or definition.default_model_family
    model_option = next((option for option in definition.model_options if option.model_id == selected_model_id), None)
    if model_option is None and definition.model_options:
        model_option = next(
            (option for option in definition.model_options if option.model_id == definition.default_model_family),
            definition.model_options[0],
        )
        selected_model_id = model_option.model_id
    selected_reasoning = None if selection is None else selection.model_reasoning_effort
    return {
        "selected_model_id": selected_model_id,
        "selected_reasoning_effort": selected_reasoning,
        "default_reasoning_effort": (
            None if model_option is None else model_option.default_reasoning_effort
        ),
        "available_models": [provider_model_option_payload(option) for option in definition.model_options],
    }


def hosted_provider_model_settings_payload(
    definition: ProviderDefinition,
    selection: ProviderHostedSelection | None,
) -> dict[str, object]:
    """Return effective hosted text model settings for a provider."""
    selected_model_id = (None if selection is None else selection.model_id) or definition.default_model_family
    model_option = next((option for option in definition.model_options if option.model_id == selected_model_id), None)
    if model_option is not None and not _provider_model_option_supports_text_output(model_option):
        model_option = None
    if model_option is None and definition.model_options:
        model_option = next(
            (
                option
                for option in definition.model_options
                if option.model_id == definition.default_model_family
                and _provider_model_option_supports_text_output(option)
            ),
            next(
                (option for option in definition.model_options if _provider_model_option_supports_text_output(option)),
                definition.model_options[0],
            ),
        )
        selected_model_id = model_option.model_id
    return {
        "selected_model_id": selected_model_id,
        "selected_reasoning_effort": None if model_option is None else model_option.default_reasoning_effort,
        "available_models": [provider_model_option_payload(option) for option in definition.model_options],
    }


def _provider_model_option_supports_text_output(option) -> bool:
    outputs = list(option.output_modalities)
    return not outputs or "text" in outputs


def _decision_failed_on_unsupported_hosted_model(decision) -> bool:
    return any(str(code).startswith("hosted_model_output_unsupported:") for code in decision.reason_codes)


def workspace_hosted_text_status(
    state: PlatformState,
    *,
    workspace_id: str,
    projection_context: ProviderProjectionContext | None = None,
) -> dict[str, object]:
    """Return workspace-scoped hosted text provider status without secret refs."""
    context = projection_context or provider_projection_context(state)
    provider_store = context.provider_store
    registry = context.registry
    available_providers = [
        provider
        for provider in registry.list_provider_definitions()
        if provider.provider_role == "model_provider"
        and provider.execution_contract is not None
        and provider.execution_contract.adapter_type == "hosted_text_generation"
    ]
    get_hosted_selection = getattr(provider_store, "get_hosted_provider_selection", None)
    selection = (
        get_hosted_selection(workspace_id=workspace_id, profile="fast_model")
        if callable(get_hosted_selection)
        else None
    )
    decision = select_provider_for_profile(
        "fast_model",
        ProviderRoutingContext(
            workspace_id=workspace_id,
            provider_store=provider_store,
            registry=registry,
            secret_store=getattr(state, "secret_store", None),
        ),
    )
    selected_provider_id = decision.selected_provider_id
    active_provider = next((provider for provider in available_providers if provider.provider_id == selected_provider_id), None)
    if active_provider is None and selection is not None and _decision_failed_on_unsupported_hosted_model(decision):
        configured_provider = next(
            (provider for provider in available_providers if provider.provider_id == selection.provider_id),
            None,
        )
        if configured_provider is not None and configured_provider.status == "active":
            active_provider = configured_provider
    active_selection = (
        selection
        if active_provider is not None
        and selection is not None
        and selection.provider_id == active_provider.provider_id
        else None
    )
    profiles = [
        _hosted_text_profile_payload(provider, model)
        for provider in sort_provider_definitions(available_providers)
        for model in provider.model_options
        if _provider_model_option_supports_text_output(model)
    ]
    return {
        "profile": "fast_model",
        "active_provider": None if active_provider is None else provider_payload(active_provider),
        "selection": hosted_provider_selection_payload(selection),
        "model_settings": (
            None
            if active_provider is None
            else hosted_provider_model_settings_payload(active_provider, active_selection)
        ),
        "available_providers": [provider_payload(provider) for provider in sort_provider_definitions(available_providers)],
        "route_preview": routing_decision_payload(decision),
        "profiles": profiles,
        "workspace_actions_message": NO_WORKSPACE_ACTIONS_MESSAGE,
    }


def _hosted_text_profile_payload(definition, model) -> dict[str, object]:
    profile, status = build_hosted_text_profile(definition, model)
    return {
        "profile": asdict(profile),
        "status": asdict(status),
        "provider": {
            "provider_id": definition.provider_id,
            "label": definition.label,
            "status": definition.status,
        },
        "model": provider_model_option_payload(model),
        "cost": dict(definition.cost_metadata),
        "selectable": status.status == "available",
        "unavailable_reason": status.reason_code,
        "workspace_actions_message": NO_WORKSPACE_ACTIONS_MESSAGE,
    }


def workspace_speech_stt_status(
    state: PlatformState,
    *,
    workspace_id: str,
    projection_context: ProviderProjectionContext | None = None,
) -> dict[str, object]:
    """Return workspace-scoped speech-to-text provider status without secret refs."""
    context = projection_context or provider_projection_context(state)
    provider_store = context.provider_store
    registry = context.registry
    available_providers = [
        provider
        for provider in registry.list_provider_definitions()
        if provider.provider_role == "speech_provider"
        and "audio" in provider.capabilities.input_modalities
        and "text" in provider.capabilities.output_modalities
    ]
    get_speech_selection = getattr(provider_store, "get_speech_provider_selection", None)
    selection = (
        get_speech_selection(workspace_id=workspace_id, profile="speech_stt")
        if callable(get_speech_selection)
        else None
    )
    active_provider = None
    active_binding = None
    if selection is not None:
        selected_provider = next(
            (provider for provider in available_providers if provider.provider_id == selection.provider_id),
            None,
        )
        selected_binding = (
            None
            if selected_provider is None
            else resolve_provider_binding(
                provider_store,
                provider_id=selected_provider.provider_id,
                workspace_id=workspace_id,
            )
        )
        if selected_provider is not None and selected_provider.status == "active" and selected_binding is not None:
            active_provider = selected_provider
            active_binding = selected_binding
    for provider in sort_provider_definitions(available_providers):
        if active_provider is not None:
            break
        binding = resolve_provider_binding(
            provider_store,
            provider_id=provider.provider_id,
            workspace_id=workspace_id,
        )
        if provider.status == "active" and binding is not None:
            active_provider = provider
            active_binding = binding
            break
    active_selection = (
        selection
        if active_provider is not None
        and selection is not None
        and selection.provider_id == active_provider.provider_id
        else None
    )
    return {
        "profile": "speech_stt",
        "active_provider": None if active_provider is None else provider_payload(active_provider),
        "credential_binding": provider_credential_binding_payload(active_binding),
        "selection": speech_provider_selection_payload(selection),
        "model_settings": (
            None
            if active_provider is None
            else speech_provider_model_settings_payload(active_provider, active_selection)
        ),
        "available_providers": [provider_payload(provider) for provider in sort_provider_definitions(available_providers)],
    }


def workspace_speech_stt_backend_provider_config(state: PlatformState, *, workspace_id: str) -> dict[str, object]:
    """Return the minimal JSON-safe Speech backend provider config."""
    return speech_stt_backend_provider_config_payload(workspace_speech_stt_status(state, workspace_id=workspace_id))


def speech_stt_backend_provider_config_payload(status: dict[str, object]) -> dict[str, object]:
    """Extract only model ids that Speech backend entrypoints consume."""
    model_settings = status.get("model_settings")
    if not isinstance(model_settings, dict):
        return {}
    config: dict[str, object] = {}
    for key in ("audio_transcription_model_id", "conversation_model_id"):
        value = str(model_settings.get(key) or "").strip()
        if value:
            config[key] = value
    return config


def speech_provider_model_settings_payload(
    definition: ProviderDefinition,
    selection: ProviderSpeechSelection | None,
) -> dict[str, object]:
    """Return effective speech provider model settings separated by use case."""
    audio_options = _speech_model_options_for_purpose(definition, "prerecorded_transcription")
    conversation_options = _speech_model_options_for_purpose(definition, "conversational_streaming")
    audio_model_id = _selected_speech_model_id(
        audio_options,
        selected_model_id=None if selection is None else selection.audio_transcription_model_id,
        preferred_model_id=str(definition.latency_metadata.get("default_audio_transcription_model_id") or ""),
        fallback_model_id=definition.default_model_family,
    )
    conversation_model_id = _selected_speech_model_id(
        conversation_options,
        selected_model_id=None if selection is None else selection.conversation_model_id,
        preferred_model_id=str(definition.latency_metadata.get("default_conversation_model_id") or ""),
        fallback_model_id="flux-general-multi",
    )
    return {
        "audio_transcription_model_id": audio_model_id,
        "conversation_model_id": conversation_model_id,
        "available_audio_transcription_models": [provider_model_option_payload(option) for option in audio_options],
        "available_conversation_models": [provider_model_option_payload(option) for option in conversation_options],
        "available_models": [provider_model_option_payload(option) for option in definition.model_options],
        "endpoints": {
            "audio_transcription": _speech_model_endpoint(audio_options, audio_model_id),
            "conversation": _speech_model_endpoint(conversation_options, conversation_model_id),
        },
    }


def _speech_model_options_for_purpose(definition: ProviderDefinition, purpose: str):
    return [
        option
        for option in definition.model_options
        if isinstance(option.metadata, dict) and option.metadata.get("purpose") == purpose
    ]


def _selected_speech_model_id(
    options,
    *,
    selected_model_id: str | None,
    preferred_model_id: str,
    fallback_model_id: str | None,
) -> str | None:
    model_ids = {option.model_id for option in options}
    for model_id in (selected_model_id, preferred_model_id, fallback_model_id):
        normalized = str(model_id or "").strip()
        if normalized and normalized in model_ids:
            return normalized
    return options[0].model_id if options else None


def _speech_model_endpoint(options, model_id: str | None) -> str | None:
    option = next((item for item in options if item.model_id == model_id), None)
    if option is None or not isinstance(option.metadata, dict):
        return None
    endpoint = option.metadata.get("endpoint")
    return str(endpoint) if endpoint else None


def runtime_session_payload(
    session: RuntimeSessionRecord,
    *,
    state: PlatformState | None = None,
    projection_context: ProviderProjectionContext | None = None,
) -> dict[str, object]:
    """Return public runtime session metadata."""
    containment_reason = remote_agentic_containment_reason(
        session.execution_binding,
        workspace_id=session.workspace_id,
        workspace_store=(
            None if state is None else getattr(state, "workspace_store", None)
        ),
    )
    payload = {
        "session_id": session.session_id,
        "workspace_id": session.workspace_id,
        "agent_id": session.agent_id,
        "status": session.status,
        "requested_mode": session.requested_mode,
        "effective_mode": session.effective_mode,
        "runtime_mode": session.runtime_mode,
        "started_at": session.started_at,
        "updated_at": session.updated_at,
        "ended_at": session.ended_at,
        "last_progress_at": session.last_progress_at,
        "recovery_reason_code": public_runtime_recovery_reason_code(
            status=session.status,
            reason_code=session.recovery_reason_code,
        ),
        "agentic_containment": {
            "status": "NO-GO" if containment_reason else "GO",
            "reason_code": containment_reason,
        },
    }
    if state is not None and session.execution_binding is not None:
        payload["agentic_governance"] = runtime_session_agentic_governance_payload(
            state,
            session=session,
            projection_context=projection_context,
        )
    return payload


def _agentic_data_destination_payload(
    *,
    provider_id: str,
    endpoint_id: str,
    upstream_provider_ids,
) -> dict[str, object]:
    upstreams = tuple(str(item) for item in upstream_provider_ids)
    routed_destination = ", ".join(upstreams)
    display_label = (
        f"{provider_id} → {routed_destination} · {endpoint_id}"
        if routed_destination
        else f"{provider_id} · {endpoint_id}"
    )
    return {
        "provider_id": provider_id,
        "endpoint_id": endpoint_id,
        "upstream_provider_ids": upstreams,
        "display_label": display_label,
    }


def _agentic_egress_policy_payload(
    *,
    policy_id: str,
    revision: str,
    policy,
) -> dict[str, object]:
    return {
        "policy_id": policy_id,
        "revision": revision,
        "allowed_remote_data_classes": policy.allowed_remote_data_classes,
    }


def _agentic_data_policy_payload(
    routing_constraint,
    *,
    egress_policy_id: str,
    egress_policy_revision: str,
    state: PlatformState | None = None,
    workspace_id: str | None = None,
) -> dict[str, object]:
    workspace_store = None if state is None else getattr(state, "workspace_store", None)
    get_attestation = getattr(workspace_store, "get_data_attestation", None)
    attestation = attestation_safe_projection(
        get_attestation(workspace_id)
        if callable(get_attestation) and workspace_id
        else None
    )
    attestation_required = remote_data_policy_requires_fake_data_attestation(
        egress_policy_id,
        egress_policy_revision,
    )
    return {
        "collection": routing_constraint.data_collection_policy,
        "require_zdr": routing_constraint.require_zdr,
        "retention": (
            "zdr_required"
            if routing_constraint.require_zdr
            else "provider_contract"
        ),
        "authority_mode": (
            "fake_data_attestation"
            if attestation_required
            else "workspace_binding"
        ),
        "attestation_required": attestation_required,
        "attestation_state": attestation["state"],
        "attestation": attestation,
    }


def workspace_provider_status(
    state: PlatformState,
    *,
    workspace_id: str,
    refresh_model_catalog: bool = False,
    actor_roles: tuple[str, str, str] | None = None,
    projection_context: ProviderProjectionContext | None = None,
) -> dict[str, object]:
    """Return the active provider state for one workspace."""
    context = projection_context or provider_projection_context(
        state,
        refresh_model_catalog=refresh_model_catalog,
    )
    provider_store = context.provider_store
    registry = context.registry
    status = resolve_workspace_provider_status(
        provider_store,
        workspace_id=workspace_id,
        workspace_store=getattr(state, "workspace_store", None),
        effective_registry=registry,
    )
    active_provider = None if status.active_provider is None else provider_payload(status.active_provider)
    native_items = context.native_items()
    agentic_profiles = workspace_agentic_profile_status(
        state,
        workspace_id=workspace_id,
        actor_roles=actor_roles,
        native_items=native_items,
        projection_context=context,
    )
    hosted_text = workspace_hosted_text_status(
        state,
        workspace_id=workspace_id,
        projection_context=context,
    )
    get_hosted_selection = getattr(
        provider_store,
        "get_hosted_provider_selection",
        None,
    )
    hosted_selection = (
        get_hosted_selection(workspace_id=workspace_id, profile="fast_model")
        if callable(get_hosted_selection)
        else None
    )
    return {
        "workspace_id": workspace_id,
        "execution_families": [
            asdict(family) for family in execution_family_catalog()
        ],
        "configured": status.configured,
        "active_provider": active_provider,
        "selection": provider_selection_payload(status.selection),
        "model_settings": None if status.active_provider is None else provider_model_settings_payload(status.active_provider, status.selection),
        "agentic_profiles": agentic_profiles,
        "native_agents": {"items": native_items},
        "hosted_text": hosted_text,
        "selection_migration": execution_family_selection_migration_payload(
            runtime_selection=status.selection,
            hosted_selection=hosted_selection,
            agentic_profile_items=agentic_profiles["items"],
        ),
        "speech_stt": workspace_speech_stt_status(
            state,
            workspace_id=workspace_id,
            projection_context=context,
        ),
        "blocked_reason": status.blocked_reason,
        "blocked_detail": status.blocked_detail,
        "available_providers": [provider_payload(provider) for provider in sort_provider_definitions(status.available_providers)],
    }


def workspace_agentic_profile_status(
    state: PlatformState,
    *,
    workspace_id: str,
    actor_roles: tuple[str, str, str] | None = None,
    native_items: list[dict[str, object]] | None = None,
    projection_context: ProviderProjectionContext | None = None,
) -> dict[str, object]:
    """Return the current selectable provider/model configs for a workspace."""
    context = projection_context or provider_projection_context(state)
    store = context.provider_store
    registry = context.registry
    native_by_engine = {
        str(item["runtime_engine_id"]): item
        for item in (native_items if native_items is not None else context.native_items())
    }
    items: list[dict[str, object]] = []
    for config in store.list_workspace_agentic_profile_bindings(workspace_id):
        if actor_roles is not None and not human_actor_selection_allowed(
            config,
            platform_role=actor_roles[0],
            user_id=actor_roles[1],
            workspace_role=actor_roles[2],
        ):
            continue
        try:
            definition = store.get_agentic_profile_definition(config.definition_id)
        except ProviderNotFoundError:
            continue
        readiness = inspect_agentic_family_readiness(
            definition=definition, binding=config, registry=registry, store=store
        )
        containment_reason = remote_agentic_containment_reason(
            definition,
            workspace_id=workspace_id,
            workspace_store=getattr(state, "workspace_store", None),
        )
        native_runtime = native_by_engine.get(definition.runtime_engine_id)
        native_ready = bool(
            readiness.execution_family != NATIVE_AGENT_EXECUTION_FAMILY
            or (native_runtime and native_runtime.get("selectable") is True)
        )
        selectable = bool(
            config.enabled and containment_reason is None and readiness.complete and native_ready
        )
        blocked_reason = (
            containment_reason
            or readiness.reason_code
            or (None if native_ready else str((native_runtime or {}).get("unavailable_reason") or "native_runtime_unavailable"))
            or (None if config.enabled else "workspace_profile_binding_disabled")
        )
        effective_capabilities = _profile_effective_capability_snapshot(
            state,
            definition=definition,
            binding=config,
            eligible=selectable,
            blocked_reason=blocked_reason,
            projection_context=context,
        )
        if selectable and effective_capabilities.get("status") != "active":
            selectable = False
            blocked_reason = str(effective_capabilities.get("reason_code") or "runtime_authority_unavailable")
        effective_policy = (
            intersect_runtime_policies(definition.policy_ceiling, config.workspace_policy_ceiling)
            if selectable else None
        )
        reasoning = _agentic_model_reasoning(registry, definition)
        try:
            research_compatible = bool(
                research_runtime_kind(
                    definition,
                    registry.get_agentic_runtime_adapter(definition.runtime_engine_id),
                )
            )
        except ProviderError:
            research_compatible = False
        items.append({
            "workspace_profile_binding_id": config.binding_id,
            "definition_id": definition.definition_id,
            "display_name": definition.display_name,
            "runtime_engine_id": definition.runtime_engine_id,
            "model_provider_id": definition.model_provider_id,
            "model_id": definition.model_id,
            "model_revision": definition.model_revision,
            "model_revision_policy": definition.model_revision_policy,
            "default_reasoning_effort": reasoning[0],
            "supported_reasoning_efforts": reasoning[1],
            "provider_protocol": definition.provider_protocol,
            "provider_api_version": definition.provider_api_version,
            "adapter_id": definition.adapter_id,
            "adapter_version_constraint": definition.adapter_version_constraint,
            "execution_family": readiness.execution_family or None,
            "runtime_status": readiness.contract_status,
            "runtime_status_reason": readiness.reason_code,
            "family_contract_status": "complete" if selectable else readiness.contract_status,
            "full_workspace_status": "available" if selectable else "unavailable",
            "rollout_status": "available" if selectable else "disabled",
            "context_policy": None if definition.context_policy is None else asdict(definition.context_policy),
            "capabilities": asdict(definition.capabilities),
            "enabled": config.enabled,
            "is_default": config.is_default,
            "credential_binding_configured": bool(config.credential_binding_id),
            "selectable": selectable,
            "unavailable_reason": None if selectable else blocked_reason,
            "containment_status": "NO-GO" if containment_reason else "GO",
            "containment_reason": containment_reason,
            "egress_policy_id": config.egress_policy_id,
            "egress_policy_revision": config.egress_policy_revision,
            "data_destination": _agentic_data_destination_payload(
                provider_id=definition.model_provider_id,
                endpoint_id=definition.routing_constraint.endpoint_id,
                upstream_provider_ids=definition.routing_constraint.allowed_upstream_ids,
            ),
            "egress_policy": _agentic_egress_policy_payload(
                policy_id=config.egress_policy_id,
                revision=config.egress_policy_revision,
                policy=config.workspace_policy_ceiling,
            ),
            "data_policy": _agentic_data_policy_payload(
                definition.routing_constraint,
                egress_policy_id=config.egress_policy_id,
                egress_policy_revision=config.egress_policy_revision,
                state=state,
                workspace_id=workspace_id,
            ),
            "allowed_remote_data_classes": config.workspace_policy_ceiling.allowed_remote_data_classes,
            "tool_handle_mode": config.workspace_policy_ceiling.tool_handle_mode,
            "allowed_tool_handles": config.workspace_policy_ceiling.allowed_tool_handles,
            "effective_tool_handle_mode": effective_policy.tool_handle_mode if effective_policy else "none",
            "effective_allowed_tool_handles": effective_policy.allowed_tool_handles if effective_policy else (),
            "max_estimated_cost_microusd": config.workspace_policy_ceiling.max_estimated_cost_microusd,
            "effective_capabilities": effective_capabilities,
            "research_compatible": research_compatible,
        })
    items.sort(key=lambda item: (not bool(item["is_default"]), str(item["display_name"])))
    default = next((item for item in items if item["selectable"] and item["is_default"]), None)
    return {
        "default_binding_id": None if default is None else default["workspace_profile_binding_id"],
        "items": items,
    }


def _profile_effective_capability_snapshot(
    state: PlatformState,
    *,
    definition,
    binding,
    eligible: bool,
    blocked_reason: str | None,
    projection_context: ProviderProjectionContext | None = None,
) -> dict[str, object]:
    """Calculate live permissions for a current provider/model config."""
    if not eligible:
        return blocked_runtime_capability_payload(
            blocked_reason or "runtime_authority_unavailable",
            profile_capabilities=definition.capabilities,
        )
    try:
        context = projection_context or provider_projection_context(state)
        registry = context.registry
        adapter = registry.get_agentic_runtime_adapter(definition.runtime_engine_id)
        governance_resolver = getattr(getattr(state, "workspace_store", None), "get_governance", None)
        if not callable(governance_resolver):
            raise AgenticRuntimeError("runtime_authority_unavailable")
        execution_mode = resolve_runtime_execution_mode(
            workspace_id=binding.workspace_id,
            governance=governance_resolver(binding.workspace_id),
            platform_allows_full_access=binding.workspace_id == "default",
        )
        runtime_policy = intersect_runtime_policies(
            definition.policy_ceiling, binding.workspace_policy_ceiling
        )
        execution_binding = build_runtime_execution_binding(
            session_id=f"capability-projection:{binding.binding_id}",
            workspace_id=binding.workspace_id,
            workspace_binding_id=binding.binding_id,
            runtime_engine_id=definition.runtime_engine_id,
            adapter_id=definition.adapter_id,
            adapter_version=str(getattr(adapter, "adapter_version", "")),
            model_provider_id=definition.model_provider_id,
            model_id=definition.model_id,
            model_revision=definition.model_revision,
            model_revision_policy=definition.model_revision_policy,
            provider_protocol=definition.provider_protocol,
            provider_api_version=definition.provider_api_version,
            routing_constraint=definition.routing_constraint,
            credential_binding_id=binding.credential_binding_id,
            reasoning_effort=definition.default_reasoning_effort,
            reasoning_efforts=definition.reasoning_efforts,
            capabilities=definition.capabilities,
            execution_mode=execution_mode,
            runtime_policy=runtime_policy,
            egress_policy_id=binding.egress_policy_id,
            egress_policy_revision=binding.egress_policy_revision,
            created_at=datetime.now(tz=UTC),
            context_policy=definition.context_policy,
        )
        health = run_runtime_coroutine(adapter.health(RuntimeHealthContext(binding=execution_binding)))
        handle_resolver = getattr(adapter, "currently_authorized_tool_handles", None)
        handles = (
            tuple(handle_resolver(execution_binding))
            if callable(handle_resolver)
            else (
                authorized_core_tool_handles(execution_binding)
                if execution_binding.runtime_engine_id == "maverick-tool-loop" else ()
            )
        )
        authority = resolve_runtime_authority(
            context.provider_store,
            binding=execution_binding,
            adapter=adapter,
            turn_id=f"capability-projection:{binding.binding_id}",
            currently_authorized_tool_handles=handles,
            live_execution_mode=execution_mode,
            health_status=health.status,
            health_revision=f"runtime-health:{canonical_digest(health)}",
            actor_policy_allowed=True,
            actor_policy_revision=f"workspace-actor:{binding.binding_id}",
        )
        return runtime_capability_payload(authority)
    except (AgenticRuntimeError, ProviderError, ValueError) as error:
        return blocked_runtime_capability_payload(
            str(getattr(error, "reason_code", None) or error),
            profile_capabilities=definition.capabilities,
        )


def _agentic_model_reasoning(
    registry,
    definition,
) -> tuple[str | None, list[dict[str, object]]]:
    """Project profile-declared reasoning choices with provider display metadata."""
    provider = None
    for provider_id in (definition.model_provider_id, definition.runtime_engine_id):
        try:
            provider = registry.get_provider_definition(provider_id)
            break
        except ProviderNotFoundError:
            continue
    model = (
        None
        if provider is None
        else next(
            (item for item in provider.model_options if item.model_id == definition.model_id),
            None,
        )
    )
    options_by_effort = {
        option.effort: option
        for option in (() if model is None else model.supported_reasoning_efforts)
    }
    declared_efforts = tuple(getattr(definition, "reasoning_efforts", ()) or ())
    if not declared_efforts and model is not None:
        declared_efforts = tuple(option.effort for option in model.supported_reasoning_efforts)
    default_effort = getattr(definition, "default_reasoning_effort", None)
    if default_effort is None and model is not None:
        default_effort = model.default_reasoning_effort
    values = []
    for effort in declared_efforts:
        option = options_by_effort.get(effort)
        values.append(
            {
                "effort": effort,
                "label": option.label if option is not None else effort.replace("_", " ").title(),
                "description": None if option is None else option.description,
            }
        )
    return default_effort, values


def workspace_agentic_admin_status(
    state: PlatformState,
    *,
    workspace_id: str,
    compact: bool = False,
    projection_context: ProviderProjectionContext | None = None,
) -> dict[str, object]:
    """Return one current administration item per provider/model config."""
    context = projection_context or provider_projection_context(state)
    store = context.provider_store
    registry = context.registry
    bindings = {
        item.definition_id: item
        for item in store.list_workspace_agentic_profile_bindings(workspace_id)
    }
    native_items = context.native_items()
    native_by_engine = {str(item["runtime_engine_id"]): item for item in native_items}
    items: list[dict[str, object]] = []
    for definition in store.list_agentic_profile_definitions():
        binding = bindings.get(definition.definition_id)
        credential_bindings = [
            provider_credential_binding_payload(item)
            for item in store.list_provider_bindings(provider_id=definition.model_provider_id)
            if item.status == "active" and item.workspace_id in {None, workspace_id}
        ]
        readiness = inspect_agentic_family_readiness(
            definition=definition, store=store, binding=binding, registry=registry
        )
        containment_reason = remote_agentic_containment_reason(
            definition,
            workspace_id=workspace_id,
            workspace_store=getattr(state, "workspace_store", None),
        )
        blocked_reason = _agentic_definition_blocked_reason(
            definition=definition,
            binding=binding,
            credential_bindings=credential_bindings,
            registry=registry,
            family_readiness=readiness,
            native_runtime=native_by_engine.get(definition.runtime_engine_id),
            containment_reason=containment_reason,
        )
        enable_blocked_reason = _agentic_definition_blocked_reason(
            definition=definition,
            binding=binding,
            credential_bindings=credential_bindings,
            registry=registry,
            family_readiness=readiness,
            native_runtime=native_by_engine.get(definition.runtime_engine_id),
            containment_reason=containment_reason,
            require_enabled_binding=False,
        )
        effective_capabilities = (
            blocked_runtime_capability_payload(
                blocked_reason or "workspace_binding_missing",
                profile_capabilities=definition.capabilities,
            )
            if binding is None else
            _profile_effective_capability_snapshot(
                state,
                definition=definition,
                binding=binding,
                eligible=blocked_reason is None,
                blocked_reason=blocked_reason,
                projection_context=context,
            )
        )
        if blocked_reason is None and effective_capabilities.get("status") != "active":
            blocked_reason = str(effective_capabilities.get("reason_code") or "runtime_authority_unavailable")
        policy = definition.policy_ceiling if binding is None else binding.workspace_policy_ceiling
        egress_id = definition.egress_policy_id if binding is None else binding.egress_policy_id
        egress_revision = definition.egress_policy_revision if binding is None else binding.egress_policy_revision
        reasoning = _agentic_model_reasoning(registry, definition)
        items.append({
            "definition_id": definition.definition_id,
            "display_name": definition.display_name,
            "runtime_engine_id": definition.runtime_engine_id,
            "model_provider_id": definition.model_provider_id,
            "model_id": definition.model_id,
            "model_revision": definition.model_revision,
            "model_revision_policy": definition.model_revision_policy,
            "default_reasoning_effort": reasoning[0],
            "supported_reasoning_efforts": reasoning[1],
            "provider_protocol": definition.provider_protocol,
            "provider_api_version": definition.provider_api_version,
            "adapter_id": definition.adapter_id,
            "adapter_version_constraint": definition.adapter_version_constraint,
            "execution_family": readiness.execution_family or None,
            "runtime_status": readiness.contract_status,
            "runtime_status_reason": readiness.reason_code,
            "context_policy": None if definition.context_policy is None else asdict(definition.context_policy),
            "capabilities": asdict(definition.capabilities),
            "routing_constraint": asdict(definition.routing_constraint),
            "upstream_provider_ids": definition.routing_constraint.allowed_upstream_ids,
            "data_destination": _agentic_data_destination_payload(
                provider_id=definition.model_provider_id,
                endpoint_id=definition.routing_constraint.endpoint_id,
                upstream_provider_ids=definition.routing_constraint.allowed_upstream_ids,
            ),
            "egress_policy": _agentic_egress_policy_payload(
                policy_id=egress_id, revision=egress_revision, policy=policy
            ),
            "data_policy": _agentic_data_policy_payload(
                definition.routing_constraint,
                egress_policy_id=egress_id,
                egress_policy_revision=egress_revision,
                state=state,
                workspace_id=workspace_id,
            ),
            "profile_policy_ceiling": asdict(definition.policy_ceiling),
            "native_runtime": native_by_engine.get(definition.runtime_engine_id),
            "credential_bindings": credential_bindings,
            "binding": None if binding is None else {
                "binding_id": binding.binding_id,
                "credential_binding_id": binding.credential_binding_id,
                "enabled": binding.enabled,
                "is_default": binding.is_default,
                "actor_policy": asdict(binding.actor_policy),
                "workspace_policy_ceiling": asdict(binding.workspace_policy_ceiling),
                "egress_policy_id": binding.egress_policy_id,
                "egress_policy_revision": binding.egress_policy_revision,
                "created_at": binding.created_at,
                "updated_at": binding.updated_at,
            },
            "health": "healthy" if blocked_reason is None else "blocked",
            "live_preflight_status": "ready" if blocked_reason is None else "unavailable",
            "live_preflight_reason": blocked_reason,
            "blocked_reason": blocked_reason,
            "selectable": blocked_reason is None,
            "enable_eligible": enable_blocked_reason is None,
            "enable_blocked_reason": enable_blocked_reason,
            "containment_status": "NO-GO" if containment_reason else "GO",
            "containment_reason": containment_reason,
            "binding_status": "missing" if binding is None else ("enabled" if binding.enabled else "disabled"),
            "effective_capabilities": effective_capabilities,
        })
    items.sort(key=lambda item: (
        not bool((item.get("binding") or {}).get("is_default")),
        str(item["display_name"]),
    ))
    return {
        "workspace_id": workspace_id,
        "execution_families": [asdict(family) for family in execution_family_catalog()],
        "native_agents": {"items": native_items},
        "release_decision": "NO-GO" if any(item["containment_status"] == "NO-GO" for item in items) else "GO",
        "items": items,
    }


def _agentic_definition_blocked_reason(
    *,
    definition,
    binding,
    credential_bindings,
    registry,
    family_readiness,
    native_runtime,
    containment_reason: str | None,
    require_enabled_binding: bool = True,
) -> str | None:
    if containment_reason is not None:
        return containment_reason
    if not family_readiness.complete:
        return family_readiness.reason_code or "runtime_unavailable"
    if (
        family_readiness.execution_family == NATIVE_AGENT_EXECUTION_FAMILY
        and (not native_runtime or native_runtime.get("selectable") is not True)
    ):
        return str((native_runtime or {}).get("unavailable_reason") or "native_runtime_unavailable")
    try:
        provider = registry.get_provider_definition(definition.model_provider_id)
    except ProviderNotFoundError:
        try:
            provider = registry.get_provider_definition(definition.runtime_engine_id)
        except ProviderNotFoundError:
            return "model_provider_unavailable"
    if require_enabled_binding:
        if binding is None:
            return "workspace_binding_missing"
        if not binding.enabled:
            return "workspace_binding_disabled"
        if provider.requires_credentials and not any(
            item and item.get("binding_id") == binding.credential_binding_id
            for item in credential_bindings
        ):
            return "credential_binding_unavailable"
    elif provider.requires_credentials and not credential_bindings:
        return "credential_binding_unavailable"
    return None


def runtime_session_agentic_governance_payload(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    projection_context: ProviderProjectionContext | None = None,
) -> dict[str, object] | None:
    """Project the concrete session config and its current live permissions."""
    binding = session.execution_binding
    if binding is None:
        return None
    context = projection_context or provider_projection_context(state)
    definition = None
    try:
        config = context.provider_store.get_workspace_agentic_profile_binding(
            binding.workspace_binding_id
        )
        definition = context.provider_store.get_agentic_profile_definition(config.definition_id)
    except ProviderNotFoundError:
        pass
    containment_reason = remote_agentic_containment_reason(
        binding,
        workspace_id=session.workspace_id,
        workspace_store=getattr(state, "workspace_store", None),
    )
    if containment_reason is not None:
        effective_capabilities = blocked_runtime_capability_payload(
            containment_reason,
            profile_capabilities=binding.capabilities_snapshot,
        )
    else:
        try:
            adapter = context.registry.get_agentic_runtime_adapter(binding.runtime_engine_id)
            authority = resolve_runtime_authority_snapshot(
                state,
                session=session,
                adapter=adapter,
                turn_id=f"capability-projection:{session.session_id}",
                provider_store=context.provider_store,
            )
            effective_capabilities = runtime_capability_payload(authority)
        except (AuthorizationError, ProviderError, ValueError) as error:
            effective_capabilities = blocked_runtime_capability_payload(
                str(getattr(error, "reason_code", None) or getattr(error, "reason", None) or error),
                profile_capabilities=binding.capabilities_snapshot,
            )
    return {
        "display_name": None if definition is None else definition.display_name,
        "workspace_binding_id": binding.workspace_binding_id,
        "runtime_engine_id": binding.runtime_engine_id,
        "adapter_id": binding.adapter_id,
        "adapter_version": binding.adapter_version,
        "context_policy": None if binding.context_policy_snapshot is None else asdict(binding.context_policy_snapshot),
        "model_provider_id": binding.model_provider_id,
        "model_id": binding.model_id,
        "model_revision": binding.model_revision,
        "model_revision_policy": binding.model_revision_policy,
        "provider_protocol": binding.provider_protocol,
        "provider_api_version": binding.provider_api_version,
        "reasoning_effort": binding.reasoning_effort,
        "containment": {
            "status": "NO-GO" if containment_reason else "GO",
            "reason_code": containment_reason,
        },
        "data_destination": _agentic_data_destination_payload(
            provider_id=binding.model_provider_id,
            endpoint_id=binding.routing_constraint_snapshot.endpoint_id,
            upstream_provider_ids=binding.routing_constraint_snapshot.allowed_upstream_ids,
        ),
        "egress_policy": _agentic_egress_policy_payload(
            policy_id=binding.egress_policy_id,
            revision=binding.egress_policy_revision,
            policy=binding.runtime_policy_snapshot,
        ),
        "data_policy": _agentic_data_policy_payload(
            binding.routing_constraint_snapshot,
            egress_policy_id=binding.egress_policy_id,
            egress_policy_revision=binding.egress_policy_revision,
            state=state,
            workspace_id=session.workspace_id,
        ),
        "effective_capabilities": effective_capabilities,
    }


def workspace_runtime_status(
    state: PlatformState,
    *,
    workspace_id: str,
    actor_roles: tuple[str, str, str] | None = None,
) -> dict[str, object]:
    """Return runtime status for one workspace."""
    context = provider_projection_context(state)
    return {
        **workspace_provider_status(
            state,
            workspace_id=workspace_id,
            actor_roles=actor_roles,
            projection_context=context,
        ),
        "sessions": [
            runtime_session_payload(
                session,
                state=state,
                projection_context=context,
            )
            for session in state.runtime_store.list_sessions(workspace_id)
        ],
    }


def provider_credential_binding_payload(binding) -> dict[str, object] | None:
    """Return public provider binding metadata without secret references."""
    if binding is None:
        return None
    return {
        "binding_id": binding.binding_id,
        "provider_id": binding.provider_id,
        "workspace_id": binding.workspace_id,
        "label": binding.label,
        "status": binding.status,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def handle_provider_api(state: PlatformState, environ: dict, start_response: StartResponse) -> list[bytes] | None:
    """Handle provider and runtime routes."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path not in {
        "/api/providers",
        "/api/providers/active",
        "/api/providers/hosted/active",
        "/api/providers/hosted/selection",
        "/api/providers/speech/active",
        "/api/providers/speech/selection",
        "/api/providers/route",
        "/api/providers/usage",
        "/api/providers/agentic/profile-definitions",
        "/api/providers/agentic/workspace-bindings",
        "/api/runtime/status",
    }:
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    if path == "/api/providers/agentic/workspace-bindings" and method == "POST":
        from core.api.http import read_json_body

        try:
            require_provider_selection_authority(
                state.workspace_store,
                user=context.user,
                workspace_id=context.workspace_id,
            )
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
        body = read_json_body(environ)
        definition_id = str(body.get("definition_id") or "").strip()
        if not definition_id:
            return json_response(
                start_response,
                {"error": "agentic_profile_definition_required"},
                status="400 Bad Request",
            )
        actor_payload = body.get("actor_policy")
        policy_patch = body.get("policy_patch")
        if not isinstance(actor_payload, dict) or not isinstance(policy_patch, dict):
            return json_response(
                start_response,
                {"error": "agentic_workspace_policy_invalid"},
                status="400 Bad Request",
            )
        try:
            actor_policy = _actor_selection_policy_from_payload(actor_payload)
            saved = save_workspace_agentic_binding(
                state.provider_store,
                effective_provider_registry(
                    state.provider_store,
                    registry=getattr(state, "provider_registry", None),
                ),
                workspace_id=context.workspace_id,
                definition_id=definition_id,
                binding_id=str(body.get("binding_id") or "").strip() or None,
                credential_binding_id=(
                    str(body.get("credential_binding_id") or "").strip() or None
                ),
                enabled=body.get("enabled") is True,
                is_default=body.get("is_default") is True,
                actor_policy=actor_policy,
                policy_patch=policy_patch,
                observability_store=state.observability_store,
                workspace_store=state.workspace_store,
            )
        except (ProviderError, ValueError) as error:
            return json_response(
                start_response,
                {"error": str(error)},
                status="400 Bad Request",
            )
        projection_context = provider_projection_context(state)
        return json_response(
            start_response,
            {
                "binding_id": saved.binding_id,
                "agentic_admin": workspace_agentic_admin_status(
                    state,
                    workspace_id=context.workspace_id,
                    projection_context=projection_context,
                ),
                "agentic_profiles": workspace_agentic_profile_status(
                    state,
                    workspace_id=context.workspace_id,
                    projection_context=projection_context,
                ),
            },
        )
    if path == "/api/providers/hosted/active" and method == "POST":
        from core.api.http import read_json_body

        if getattr(context.user, "platform_role", None) != "admin":
            return json_response(start_response, {"error": "provider_hosted_activation_forbidden"}, status="403 Forbidden")
        body = read_json_body(environ)
        provider_id = str(body.get("provider_id") or "").strip()
        secret_ref = str(body.get("secret_ref") or "").strip()
        if not provider_id:
            return json_response(start_response, {"error": "missing_provider_id"}, status="400 Bad Request")
        if not secret_ref:
            return json_response(start_response, {"error": "missing_secret_ref"}, status="400 Bad Request")
        if str(body.get("binding_id") or "").strip():
            return json_response(start_response, {"error": "binding_id_not_supported"}, status="400 Bad Request")
        try:
            activation = activate_hosted_model_provider(
                state.provider_store,
                secret_store=state.secret_store,
                workspace_id=context.workspace_id,
                provider_id=provider_id,
                secret_ref=secret_ref,
                label=str(body.get("label") or "").strip() or None,
                registry=getattr(state, "provider_registry", None),
                observability_store=state.observability_store,
            )
        except Exception as error:
            return json_response(
                start_response,
                {"error": "hosted_provider_activation_failed", "error_type": type(error).__name__},
                status="400 Bad Request",
            )
        return json_response(
            start_response,
            {
                "workspace_id": context.workspace_id,
                "provider": provider_payload(activation.definition),
                "credential_binding": provider_credential_binding_payload(activation.credential_binding),
                "hosted_selection": hosted_provider_selection_payload(activation.hosted_selection),
                "preflight": routing_decision_payload(activation.routing_decision),
            },
        )
    if path == "/api/providers/speech/active" and method == "POST":
        from core.api.http import read_json_body

        if getattr(context.user, "platform_role", None) != "admin":
            return json_response(start_response, {"error": "provider_speech_activation_forbidden"}, status="403 Forbidden")
        body = read_json_body(environ)
        provider_id = str(body.get("provider_id") or "").strip()
        secret_ref = str(body.get("secret_ref") or "").strip()
        if not provider_id:
            return json_response(start_response, {"error": "missing_provider_id"}, status="400 Bad Request")
        if not secret_ref:
            return json_response(start_response, {"error": "missing_secret_ref"}, status="400 Bad Request")
        try:
            activation = activate_speech_provider(
                state.provider_store,
                secret_store=state.secret_store,
                workspace_id=context.workspace_id,
                provider_id=provider_id,
                secret_ref=secret_ref,
                label=str(body.get("label") or "").strip() or None,
                registry=getattr(state, "provider_registry", None),
                observability_store=state.observability_store,
            )
        except Exception as error:
            return json_response(
                start_response,
                {"error": "speech_provider_activation_failed", "error_type": type(error).__name__},
                status="400 Bad Request",
            )
        return json_response(
            start_response,
            {
                "workspace_id": context.workspace_id,
                "provider": provider_payload(activation.definition),
                "credential_binding": provider_credential_binding_payload(activation.credential_binding),
                "speech_selection": speech_provider_selection_payload(activation.speech_selection),
                "speech_stt": workspace_speech_stt_status(state, workspace_id=context.workspace_id),
            },
        )
    if path == "/api/providers/speech/selection" and method == "POST":
        from core.api.http import read_json_body

        body = read_json_body(environ)
        provider_id = str(body.get("provider_id") or "").strip()
        if not provider_id:
            return json_response(start_response, {"error": "missing_provider_id"}, status="400 Bad Request")
        try:
            require_provider_selection_authority(state.workspace_store, user=context.user, workspace_id=context.workspace_id)
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
        try:
            configure_speech_provider(
                state.provider_store,
                workspace_id=context.workspace_id,
                provider_id=provider_id,
                audio_transcription_model_id=str(body.get("audio_transcription_model_id") or "").strip() or None,
                conversation_model_id=str(body.get("conversation_model_id") or "").strip() or None,
                registry=getattr(state, "provider_registry", None),
                observability_store=state.observability_store,
            )
        except Exception as error:
            return json_response(start_response, {"error": str(error)}, status="400 Bad Request")
        return json_response(
            start_response,
            workspace_provider_status(
                state,
                workspace_id=context.workspace_id,
                actor_roles=_request_actor_roles(state, context),
            ),
        )
    if path == "/api/providers/hosted/selection" and method == "POST":
        from core.api.http import read_json_body

        body = read_json_body(environ)
        provider_id = str(body.get("provider_id") or "").strip()
        if not provider_id:
            return json_response(start_response, {"error": "missing_provider_id"}, status="400 Bad Request")
        try:
            require_provider_selection_authority(state.workspace_store, user=context.user, workspace_id=context.workspace_id)
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
        model_id = str(body.get("model_id") or "").strip() or None
        openrouter_provider_routing = (
            body.get("openrouter_provider_routing")
            if isinstance(body.get("openrouter_provider_routing"), dict)
            else None
        )
        try:
            configure_hosted_model_provider(
                state.provider_store,
                workspace_id=context.workspace_id,
                provider_id=provider_id,
                model_id=model_id,
                openrouter_provider_routing=openrouter_provider_routing,
                registry=getattr(state, "provider_registry", None),
                observability_store=state.observability_store,
            )
        except Exception as error:
            return json_response(start_response, {"error": str(error)}, status="400 Bad Request")
        return json_response(
            start_response,
            workspace_provider_status(
                state,
                workspace_id=context.workspace_id,
                actor_roles=_request_actor_roles(state, context),
            ),
        )
    if path == "/api/providers/active" and method == "POST":
        from core.api.http import read_json_body

        body = read_json_body(environ)
        provider_id = str(body.get("provider_id") or "").strip()
        if not provider_id:
            return json_response(start_response, {"error": "missing_provider_id"}, status="400 Bad Request")
        try:
            require_provider_selection_authority(state.workspace_store, user=context.user, workspace_id=context.workspace_id)
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
        model_id = str(body.get("model_id") or "").strip() or None
        model_reasoning_effort = str(body.get("model_reasoning_effort") or "").strip() or None
        try:
            configure_workspace_agentic_default(
                state.provider_store,
                effective_provider_registry(
                    state.provider_store,
                    registry=getattr(state, "provider_registry", None),
                    refresh_model_catalog=True,
                ),
                workspace_id=context.workspace_id,
                provider_id=provider_id,
                model_id=model_id,
                model_reasoning_effort=model_reasoning_effort,
                observability_store=state.observability_store,
            )
        except Exception as error:
            return json_response(start_response, {"error": str(error)}, status="400 Bad Request")
        return json_response(
            start_response,
            workspace_provider_status(
                state,
                workspace_id=context.workspace_id,
                actor_roles=_request_actor_roles(state, context),
            ),
        )
    if method != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if path == "/api/providers/usage":
        if getattr(context.user, "platform_role", None) != "admin":
            return json_response(start_response, {"error": "provider_usage_forbidden"}, status="403 Forbidden")
        usages = read_workspace_provider_subscription_usage(
            state.provider_store,
            workspace_id=context.workspace_id,
            workspace_store=getattr(state, "workspace_store", None),
        )
        with suppress(Exception):
            record_provider_quota_snapshots(
                state.usage_store,
                workspace_id=context.workspace_id,
                usages=usages,
            )
        return json_response(
            start_response,
            {
                "workspace_id": context.workspace_id,
                "items": [provider_subscription_usage_payload(usage) for usage in usages],
            },
        )
    if path in {
        "/api/providers/agentic/profile-definitions",
    }:
        try:
            require_provider_selection_authority(
                state.workspace_store,
                user=context.user,
                workspace_id=context.workspace_id,
            )
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    if path == "/api/providers/agentic/profile-definitions":
        definitions = state.provider_store.list_agentic_profile_definitions()
        return json_response(
            start_response,
            {
                "items": [
                    {
                        "definition_id": item.definition_id,
                        "display_name": item.display_name,
                        "runtime_engine_id": item.runtime_engine_id,
                        "model_provider_id": item.model_provider_id,
                        "model_id": item.model_id,
                        "provider_protocol": item.provider_protocol,
                        "provider_api_version": item.provider_api_version,
                        "adapter_id": item.adapter_id,
                        "adapter_version_constraint": item.adapter_version_constraint,
                        "routing_constraint": asdict(item.routing_constraint),
                        "capabilities": asdict(item.capabilities),
                        "reasoning_efforts": item.reasoning_efforts,
                        "default_reasoning_effort": item.default_reasoning_effort,
                        "created_at": item.created_at,
                    }
                    for item in definitions
                ]
            },
        )
    if path == "/api/providers/agentic/workspace-bindings":
        try:
            require_provider_selection_authority(
                state.workspace_store,
                user=context.user,
                workspace_id=context.workspace_id,
            )
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
        return json_response(
            start_response,
            workspace_agentic_admin_status(state, workspace_id=context.workspace_id),
        )
    if path == "/api/providers":
        provider_status = workspace_provider_status(
            state,
            workspace_id=context.workspace_id,
            refresh_model_catalog=True,
            actor_roles=_request_actor_roles(state, context),
        )
        return json_response(
            start_response,
            {
                "items": provider_status["available_providers"],
                **provider_status,
            },
        )
    if path == "/api/providers/route":
        params = query_params(environ)
        decision = select_provider_for_profile(
            params.get("profile") or "fast_model",
            ProviderRoutingContext(
                workspace_id=context.workspace_id,
                provider_store=state.provider_store,
                registry=effective_provider_registry(
                    state.provider_store,
                    registry=getattr(state, "provider_registry", None),
                ),
                secret_store=state.secret_store,
                request_id=params.get("request_id"),
                user_tier=params.get("user_tier"),
                app_id=params.get("app_id"),
                allow_fallback_codex=str(params.get("allow_fallback_codex") or "").lower() in {"1", "true", "yes"},
            ),
        )
        return json_response(start_response, {"decision": routing_decision_payload(decision)})
    if path == "/api/providers/active":
        return json_response(
            start_response,
            workspace_provider_status(
                state,
                workspace_id=context.workspace_id,
                actor_roles=_request_actor_roles(state, context),
            ),
        )
    if path == "/api/runtime/status":
        return json_response(
            start_response,
            workspace_runtime_status(
                state,
                workspace_id=context.workspace_id,
                actor_roles=_request_actor_roles(state, context),
            ),
        )
    return None


def _actor_selection_policy_from_payload(payload: dict) -> ActorSelectionPolicy:
    def string_tuple(key: str) -> tuple[str, ...]:
        value = payload.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"agentic_actor_{key}_invalid")
        normalized = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) > 100:
            raise ValueError(f"agentic_actor_{key}_too_large")
        return normalized

    return ActorSelectionPolicy(
        allow_workspace_admins=payload.get("allow_workspace_admins") is True,
        allowed_user_ids=string_tuple("allowed_user_ids"),
        allowed_workspace_role_ids=string_tuple("allowed_workspace_role_ids"),
        allowed_agent_type_ids=string_tuple("allowed_agent_type_ids"),
    )


def _request_actor_roles(
    state: PlatformState,
    context: RequestSession,
) -> tuple[str, str, str]:
    """Project the authority already established for the authenticated request."""
    platform_role = str(getattr(context.user, "platform_role", "") or "")
    user_id = str(context.user.user_id)
    if platform_role == "admin":
        return platform_role, user_id, "admin"
    get_membership = getattr(state.workspace_store, "get_membership", None)
    if not callable(get_membership):
        return platform_role, user_id, ""
    try:
        membership = get_membership(
            user_id=user_id,
            workspace_id=context.workspace_id,
        )
    except Exception:
        return platform_role, user_id, ""
    workspace_role = membership.role if membership.status == "active" else ""
    return platform_role, user_id, workspace_role
