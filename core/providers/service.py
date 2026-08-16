"""Provider-domain service facade and builtin provider bootstrap."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from inspect import signature

from core.observability.service import record_platform_audit, record_platform_event
from core.providers.agentic_profiles import (
    ensure_codex_workspace_profile,
    provider_selection_from_execution_binding,
)
from core.providers.errors import (
    ProviderCapabilityError,
    ProviderError,
    ProviderNotFoundError,
    ProviderSelectionError,
    ProviderUsageUnavailableError,
)
from core.providers.models import (
    ProviderCredentialBinding,
    ProviderDefinition,
    ProviderHostedSelection,
    ProviderSelection,
    ProviderSpeechSelection,
    ProviderSubscriptionUsage,
    RoutingDecision,
    RuntimeBackendLaunchSpec,
    WorkspaceProviderStatus,
)
from core.providers.provider_codex import CodexProviderAdapter, build_codex_definition
from core.providers.provider_hosted_metadata import build_hosted_provider_definitions
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.provider_credentials import bind_provider_credential, disable_provider_binding
from core.providers.provider_registry import ProviderRegistry, RuntimeBackendAdapter
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.provider_selection import ProviderSelectionService
from core.providers.store import ProviderStore
from core.runtime.runtime_session import RuntimeSessionRecord
from core.secrets.errors import SecretBindingError
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import parse_secret_ref
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.store import SecretStore
from core.skills.models import SkillDefinition, SkillMaterialization


RETIRED_PROVIDER_IDS = {"deepseek", "groq"}


@dataclass(frozen=True)
class HostedModelProviderActivation:
    """Result of operator activation for a hosted model provider."""

    definition: ProviderDefinition
    credential_binding: ProviderCredentialBinding | None
    hosted_selection: ProviderHostedSelection | None
    routing_decision: RoutingDecision


@dataclass(frozen=True)
class SpeechProviderActivation:
    """Result of operator activation for a speech provider."""

    definition: ProviderDefinition
    credential_binding: ProviderCredentialBinding
    speech_selection: ProviderSpeechSelection | None


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def builtin_provider_registry(*, codex_command: str | None = None, refresh_model_catalog: bool = False) -> ProviderRegistry:
    """Build the builtin provider registry shipped by the core."""
    registry = ProviderRegistry()
    adapter = CodexProviderAdapter(codex_command=codex_command)
    registry.register_runtime_adapter(adapter)
    for definition in build_hosted_provider_definitions():
        registry.register_provider_definition(definition)
    if refresh_model_catalog:
        options = adapter.model_options(refresh=True)
        registry.register_provider_definition(
            build_codex_definition(
                model_options=options,
                default_model_id=adapter.default_model_id(options),
            )
        )
    return registry


def register_builtin_providers(
    store: ProviderStore,
    *,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    refresh_model_catalog: bool = False,
) -> list[ProviderDefinition]:
    """Persist builtin provider definitions into the provider store."""
    active_registry = registry or builtin_provider_registry(
        codex_command=codex_command,
        refresh_model_catalog=refresh_model_catalog,
    )
    definitions = active_registry.list_provider_definitions()
    for definition in definitions:
        try:
            existing = store.get_provider_definition(definition.provider_id)
        except ProviderNotFoundError:
            store.save_provider_definition(definition)
            continue
        refreshed_model_options = definition.model_options
        refreshed_default_model_family = definition.default_model_family
        if _should_preserve_existing_codex_model_catalog(
            existing,
            definition,
            refresh_model_catalog=refresh_model_catalog,
        ):
            refreshed_model_options = existing.model_options
            refreshed_default_model_family = existing.default_model_family
        refreshed_definition = replace(
            definition,
            status=existing.status,
            created_at=existing.created_at,
            updated_at=existing.updated_at,
            default_model_family=refreshed_default_model_family,
            model_options=refreshed_model_options,
        )
        if refreshed_definition != existing:
            store.save_provider_definition(refreshed_definition)
    return definitions


def _should_preserve_existing_codex_model_catalog(
    existing: ProviderDefinition,
    incoming: ProviderDefinition,
    *,
    refresh_model_catalog: bool,
) -> bool:
    if refresh_model_catalog or incoming.provider_id != "codex":
        return False
    incoming_model_ids = [option.model_id for option in incoming.model_options]
    existing_model_ids = [option.model_id for option in existing.model_options]
    if len(incoming_model_ids) != 1 or not _is_codex_fallback_model_catalog(incoming):
        return False
    return bool(
        existing_model_ids
        and existing_model_ids != incoming_model_ids
        and not _is_codex_fallback_model_catalog(existing)
    )


def _is_codex_fallback_model_catalog(definition: ProviderDefinition) -> bool:
    if definition.provider_id != "codex" or len(definition.model_options) != 1:
        return False
    description = definition.model_options[0].description or ""
    return description.startswith("Default Codex model configured")


def effective_provider_registry(
    store: ProviderStore,
    *,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    refresh_model_catalog: bool = False,
) -> ProviderRegistry:
    """Return builtin provider metadata overlaid with persisted store definitions."""
    active_registry = registry or builtin_provider_registry(
        codex_command=codex_command,
        refresh_model_catalog=refresh_model_catalog,
    )
    register_builtin_providers(
        store,
        registry=active_registry,
        codex_command=codex_command,
        refresh_model_catalog=refresh_model_catalog,
    )
    for definition in store.list_provider_definitions():
        if is_retired_provider_definition(definition):
            continue
        active_registry.register_provider_definition(definition)
    return active_registry


def is_retired_provider_definition(definition: ProviderDefinition) -> bool:
    """Return whether a persisted provider definition should no longer be exposed."""
    return definition.provider_id in RETIRED_PROVIDER_IDS


def activate_hosted_model_provider(
    store: ProviderStore,
    *,
    secret_store: SecretStore,
    workspace_id: str,
    provider_id: str,
    secret_ref: str,
    label: str | None = None,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    observability_store=None,
    now: datetime | None = None,
) -> HostedModelProviderActivation:
    """Activate one hosted text model provider and bind its credential metadata."""
    active_registry = effective_provider_registry(
        store,
        registry=registry,
        codex_command=codex_command,
        refresh_model_catalog=True,
    )
    definition = active_registry.get_provider_definition(provider_id)
    _validate_hosted_model_provider(definition)
    _assert_secret_ref_exists(secret_store, secret_ref)
    timestamp = now or utcnow()
    active_definition = store.save_provider_definition(replace(definition, status="active", updated_at=timestamp))
    binding = bind_provider_credential(
        store,
        provider_id=provider_id,
        secret_ref=secret_ref,
        workspace_id=workspace_id,
        label=label,
        observability_store=observability_store,
        now=timestamp,
    )
    hosted_selection = configure_hosted_model_provider(
        store,
        workspace_id=workspace_id,
        provider_id=provider_id,
        model_id=definition.default_model_family,
        selection_reason="activated by hosted provider operator",
        registry=active_registry,
        codex_command=codex_command,
        observability_store=observability_store,
        now=timestamp,
    )
    routing_registry = effective_provider_registry(store, registry=active_registry, codex_command=codex_command)
    decision = select_provider_for_profile(
        "fast_model",
        ProviderRoutingContext(
            workspace_id=workspace_id,
            provider_store=store,
            registry=routing_registry,
            secret_store=secret_store,
        ),
    )
    if observability_store is not None:
        payload = {
            "workspace_id": workspace_id,
            "provider_id": provider_id,
            "binding_id": binding.binding_id,
            "preflight_selected_provider_id": decision.selected_provider_id,
            "preflight_execution_path": decision.execution_path,
            "preflight_reason_codes": decision.reason_codes,
        }
        record_platform_audit(
            observability_store,
            action="provider.hosted.activate",
            status="succeeded",
            source_domain="providers",
            detail=f"Activated hosted provider `{provider_id}` for workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
            now=timestamp,
        )
        record_platform_event(
            observability_store,
            event_type="provider.hosted.activated",
            event_plane="platform",
            source_domain="providers",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
            now=timestamp,
        )
    return HostedModelProviderActivation(
        definition=active_definition,
        credential_binding=binding,
        hosted_selection=hosted_selection,
        routing_decision=decision,
    )


def activate_speech_provider(
    store: ProviderStore,
    *,
    secret_store: SecretStore,
    workspace_id: str,
    provider_id: str,
    secret_ref: str,
    label: str | None = None,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    observability_store=None,
    now: datetime | None = None,
) -> SpeechProviderActivation:
    """Activate one remote speech provider and bind its credential metadata."""
    active_registry = effective_provider_registry(
        store,
        registry=registry,
        codex_command=codex_command,
        refresh_model_catalog=True,
    )
    definition = active_registry.get_provider_definition(provider_id)
    _validate_speech_provider(definition)
    _assert_secret_ref_exists(secret_store, secret_ref)
    timestamp = now or utcnow()
    active_definition = store.save_provider_definition(replace(definition, status="active", updated_at=timestamp))
    binding = bind_provider_credential(
        store,
        provider_id=provider_id,
        secret_ref=secret_ref,
        workspace_id=workspace_id,
        label=label,
        observability_store=observability_store,
        now=timestamp,
    )
    speech_selection = configure_speech_provider(
        store,
        workspace_id=workspace_id,
        provider_id=provider_id,
        audio_transcription_model_id=str(definition.latency_metadata.get("default_audio_transcription_model_id") or ""),
        conversation_model_id=str(definition.latency_metadata.get("default_conversation_model_id") or ""),
        selection_reason="activated by speech provider operator",
        registry=active_registry,
        codex_command=codex_command,
        observability_store=observability_store,
        now=timestamp,
    )
    if observability_store is not None:
        payload = {"workspace_id": workspace_id, "provider_id": provider_id, "binding_id": binding.binding_id}
        record_platform_audit(
            observability_store,
            action="provider.speech.activate",
            status="succeeded",
            source_domain="providers",
            detail=f"Activated speech provider `{provider_id}` for workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
            now=timestamp,
        )
        record_platform_event(
            observability_store,
            event_type="provider.speech.activated",
            event_plane="platform",
            source_domain="providers",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
            now=timestamp,
        )
    return SpeechProviderActivation(
        definition=active_definition,
        credential_binding=binding,
        speech_selection=speech_selection,
    )


def configure_speech_provider(
    store: ProviderStore,
    *,
    workspace_id: str,
    provider_id: str,
    audio_transcription_model_id: str | None = None,
    conversation_model_id: str | None = None,
    profile: str = "speech_stt",
    selection_reason: str = "configured by speech provider settings",
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    observability_store=None,
    now: datetime | None = None,
) -> ProviderSpeechSelection:
    """Persist speech provider model choices for one workspace profile."""
    if profile != "speech_stt":
        raise ProviderCapabilityError(f"Speech provider profile `{profile}` is not supported.")
    active_registry = effective_provider_registry(store, registry=registry, codex_command=codex_command)
    definition = active_registry.get_provider_definition(provider_id)
    _validate_speech_provider(definition)
    if definition.status != "active":
        raise ProviderCapabilityError(f"Speech provider `{provider_id}` is not active.")
    timestamp = now or utcnow()
    previous = store.get_speech_provider_selection(workspace_id=workspace_id, profile="speech_stt")
    audio_model_id = _speech_selection_model_id(
        definition,
        requested_model_id=audio_transcription_model_id,
        previous_model_id=None if previous is None else previous.audio_transcription_model_id,
        purpose="prerecorded_transcription",
        preferred_model_id=str(definition.latency_metadata.get("default_audio_transcription_model_id") or ""),
    )
    conversation_model = _speech_selection_model_id(
        definition,
        requested_model_id=conversation_model_id,
        previous_model_id=None if previous is None else previous.conversation_model_id,
        purpose="conversational_streaming",
        preferred_model_id=str(definition.latency_metadata.get("default_conversation_model_id") or ""),
    )
    selection = ProviderSpeechSelection(
        selection_id=f"{workspace_id}:{profile}",
        workspace_id=workspace_id,
        profile="speech_stt",
        provider_id=provider_id,
        selection_reason=selection_reason,
        created_at=timestamp,
        updated_at=timestamp,
        audio_transcription_model_id=audio_model_id,
        conversation_model_id=conversation_model,
    )
    saved = store.save_speech_provider_selection(selection)
    if observability_store is not None:
        payload = {
            "workspace_id": workspace_id,
            "profile": profile,
            "provider_id": provider_id,
            "audio_transcription_model_id": saved.audio_transcription_model_id,
            "conversation_model_id": saved.conversation_model_id,
        }
        record_platform_audit(
            observability_store,
            action="provider.speech.selection.configure",
            status="succeeded",
            source_domain="providers",
            detail=f"Configured speech provider `{provider_id}` for workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
            now=timestamp,
        )
        record_platform_event(
            observability_store,
            event_type="provider.speech.selection.configured",
            event_plane="platform",
            source_domain="providers",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
            now=timestamp,
        )
    return saved


def configure_hosted_model_provider(
    store: ProviderStore,
    *,
    workspace_id: str,
    provider_id: str,
    model_id: str | None = None,
    openrouter_provider_routing: dict[str, object] | None = None,
    profile: str = "fast_model",
    selection_reason: str = "configured by hosted model settings",
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    observability_store=None,
    now: datetime | None = None,
) -> ProviderHostedSelection:
    """Persist the selected hosted text provider/model for one workspace profile."""
    if profile != "fast_model":
        raise ProviderCapabilityError(f"Hosted provider profile `{profile}` is not supported.")
    active_registry = effective_provider_registry(store, registry=registry, codex_command=codex_command)
    definition = active_registry.get_provider_definition(provider_id)
    _validate_hosted_model_provider(definition)
    if definition.status != "active":
        raise ProviderCapabilityError(f"Hosted provider `{provider_id}` is not active.")
    normalized_model_id = _validate_hosted_model_id(definition, model_id)
    timestamp = now or utcnow()
    previous = store.get_hosted_provider_selection(workspace_id=workspace_id, profile="fast_model")
    routing_by_model = dict(previous.openrouter_provider_routing_by_model) if previous is not None else {}
    if normalized_model_id:
        routing_by_model[normalized_model_id] = _normalize_openrouter_provider_routing(openrouter_provider_routing)
    selected_model_id = _hosted_text_selection_model_id(
        definition,
        requested_model_id=normalized_model_id,
        previous_model_id=None if previous is None else previous.model_id,
    )
    selection = ProviderHostedSelection(
        selection_id=f"{workspace_id}:{profile}",
        workspace_id=workspace_id,
        profile="fast_model",
        provider_id=provider_id,
        selection_reason=selection_reason,
        created_at=timestamp,
        updated_at=timestamp,
        model_id=selected_model_id,
        openrouter_provider_routing_by_model=routing_by_model,
    )
    saved = store.save_hosted_provider_selection(selection)
    if observability_store is not None:
        payload = {
            "workspace_id": workspace_id,
            "profile": profile,
            "provider_id": provider_id,
            "model_id": saved.model_id,
            "openrouter_provider_routing": (
                saved.openrouter_provider_routing_by_model.get(saved.model_id or "")
                if saved.model_id
                else None
            ),
        }
        record_platform_audit(
            observability_store,
            action="provider.hosted.selection.configure",
            status="succeeded",
            source_domain="providers",
            detail=f"Configured hosted provider `{provider_id}` for workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
            now=timestamp,
        )
        record_platform_event(
            observability_store,
            event_type="provider.hosted.selection.configured",
            event_plane="platform",
            source_domain="providers",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
            now=timestamp,
        )
    return saved


def _normalize_openrouter_provider_routing(value: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"mode": "auto"}
    mode = str(value.get("mode") or "auto").strip()
    if mode not in {"auto", "prefer", "only", "ignore"}:
        mode = "auto"
    provider_id = str(value.get("provider_id") or "").strip()
    sort = str(value.get("sort") or "").strip()
    if sort not in {"", "price", "throughput", "latency"}:
        sort = ""
    data_collection = str(value.get("data_collection") or "").strip()
    if data_collection not in {"", "allow", "deny"}:
        data_collection = ""
    quantizations = [
        str(item).strip()
        for item in (value.get("quantizations") if isinstance(value.get("quantizations"), list) else [])
        if str(item).strip()
    ]
    normalized: dict[str, object] = {"mode": mode}
    if mode != "auto" and provider_id:
        normalized["provider_id"] = provider_id
    normalized["allow_fallbacks"] = bool(value.get("allow_fallbacks", True))
    normalized["require_parameters"] = bool(value.get("require_parameters", False))
    if sort:
        normalized["sort"] = sort
    if data_collection:
        normalized["data_collection"] = data_collection
    if quantizations:
        normalized["quantizations"] = quantizations[:4]
    return normalized


def _validate_hosted_model_provider(definition: ProviderDefinition) -> None:
    if definition.kind != "hosted_api":
        raise ProviderCapabilityError(f"Provider `{definition.provider_id}` is not a hosted API provider.")
    if definition.provider_role != "model_provider":
        raise ProviderCapabilityError(f"Provider `{definition.provider_id}` is not a hosted model provider.")
    if definition.execution_contract is None or definition.execution_contract.adapter_type != "hosted_text_generation":
        raise ProviderCapabilityError(f"Provider `{definition.provider_id}` does not support hosted text generation.")


def _validate_speech_provider(definition: ProviderDefinition) -> None:
    if definition.kind != "hosted_api":
        raise ProviderCapabilityError(f"Provider `{definition.provider_id}` is not a hosted API provider.")
    if definition.provider_role != "speech_provider":
        raise ProviderCapabilityError(f"Provider `{definition.provider_id}` is not a speech provider.")
    if "audio" not in definition.capabilities.input_modalities or "text" not in definition.capabilities.output_modalities:
        raise ProviderCapabilityError(f"Provider `{definition.provider_id}` does not support speech-to-text.")


def _validate_hosted_model_id(definition: ProviderDefinition, model_id: str | None) -> str | None:
    normalized_model_id = str(model_id or "").strip() or definition.default_model_family
    if normalized_model_id is None:
        return None
    model_ids = {option.model_id for option in definition.model_options}
    if model_ids and normalized_model_id not in model_ids:
        raise ProviderCapabilityError(
            f"Model `{normalized_model_id}` is not declared by hosted provider `{definition.provider_id}`."
        )
    return normalized_model_id


def _speech_selection_model_id(
    definition: ProviderDefinition,
    *,
    requested_model_id: str | None,
    previous_model_id: str | None,
    purpose: str,
    preferred_model_id: str,
) -> str | None:
    requested = str(requested_model_id or "").strip()
    if _speech_model_supports_purpose(definition, requested, purpose=purpose):
        return requested
    if requested:
        raise ProviderCapabilityError(
            f"Model `{requested}` is not declared by speech provider `{definition.provider_id}` for `{purpose}`."
        )
    previous = str(previous_model_id or "").strip()
    if _speech_model_supports_purpose(definition, previous, purpose=purpose):
        return previous
    preferred = str(preferred_model_id or "").strip()
    if _speech_model_supports_purpose(definition, preferred, purpose=purpose):
        return preferred
    for option in definition.model_options:
        if _model_option_supports_purpose(option, purpose=purpose):
            return option.model_id
    return None


def _speech_model_supports_purpose(definition: ProviderDefinition, model_id: str, *, purpose: str) -> bool:
    if not model_id:
        return False
    option = next((option for option in definition.model_options if option.model_id == model_id), None)
    return option is not None and _model_option_supports_purpose(option, purpose=purpose)


def _model_option_supports_purpose(option, *, purpose: str) -> bool:
    metadata = getattr(option, "metadata", {})
    return isinstance(metadata, dict) and metadata.get("purpose") == purpose


def _hosted_text_selection_model_id(
    definition: ProviderDefinition,
    *,
    requested_model_id: str | None,
    previous_model_id: str | None,
) -> str | None:
    if _hosted_model_supports_text_output(definition, requested_model_id):
        return requested_model_id
    if _hosted_model_supports_text_output(definition, previous_model_id):
        return previous_model_id
    if _hosted_model_supports_text_output(definition, definition.default_model_family):
        return definition.default_model_family
    for option in definition.model_options:
        if _model_option_supports_text_output(option):
            return option.model_id
    return requested_model_id


def _hosted_model_supports_text_output(definition: ProviderDefinition, model_id: str | None) -> bool:
    if not model_id:
        return False
    option = next((option for option in definition.model_options if option.model_id == model_id), None)
    return option is not None and _model_option_supports_text_output(option)


def _model_option_supports_text_output(option) -> bool:
    outputs = list(option.output_modalities)
    return not outputs or "text" in outputs


def _assert_secret_ref_exists(secret_store: SecretStore, secret_ref: str) -> None:
    parsed = parse_secret_ref(secret_ref)
    if parsed.kind == "secret_id":
        secret_store.get_secret(parsed.value)
    else:
        secret_store.get_secret_by_alias(parsed.value)


def list_available_providers(
    store: ProviderStore,
    *,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    refresh_model_catalog: bool = False,
) -> list[ProviderDefinition]:
    """List provider definitions from the authoritative registry."""
    active_registry = effective_provider_registry(
        store,
        registry=registry,
        codex_command=codex_command,
        refresh_model_catalog=refresh_model_catalog,
    )
    return active_registry.list_provider_definitions()


def configure_workspace_provider(
    store: ProviderStore,
    *,
    workspace_id: str,
    provider_id: str,
    binding_id: str | None = None,
    model_id: str | None = None,
    model_reasoning_effort: str | None = None,
    selection_reason: str = "configured by control-plane policy",
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    observability_store=None,
    now: datetime | None = None,
) -> ProviderSelection:
    """Persist the selected runtime provider for one workspace."""
    active_registry = registry or builtin_provider_registry(
        codex_command=codex_command,
        refresh_model_catalog=True,
    )
    register_builtin_providers(
        store,
        registry=active_registry,
        codex_command=codex_command,
        refresh_model_catalog=True,
    )
    normalized_model_id = str(model_id or "").strip() or None
    normalized_reasoning_effort = str(model_reasoning_effort or "").strip() or None
    adapter = active_registry.get_runtime_adapter(provider_id)
    validate_model_settings = getattr(adapter, "validate_model_settings", None)
    if callable(validate_model_settings):
        normalized_model_id, normalized_reasoning_effort = validate_model_settings(
            normalized_model_id,
            normalized_reasoning_effort,
        )
    service = ProviderSelectionService(store, active_registry)
    selection = service.configure_workspace_provider(
        workspace_id=workspace_id,
        provider_id=provider_id,
        binding_id=binding_id,
        model_id=normalized_model_id,
        model_reasoning_effort=normalized_reasoning_effort,
        selection_reason=selection_reason,
        now=now,
    )
    if provider_id == "codex":
        ensure_codex_workspace_profile(
            store,
            definition=active_registry.get_provider_definition(provider_id),
            selection=selection,
            now=now,
        )
    if observability_store is not None:
        record_platform_audit(
            observability_store,
            action="provider.selection.configure",
            status="succeeded",
            source_domain="providers",
            detail=f"Configured provider `{provider_id}` for workspace `{workspace_id}`.",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload={
                "workspace_id": workspace_id,
                "provider_id": provider_id,
                "binding_id": selection.binding_id,
                "model_id": selection.model_id,
                "model_reasoning_effort": selection.model_reasoning_effort,
            },
        )
        record_platform_event(
            observability_store,
            event_type="provider.selection.configured",
            event_plane="platform",
            source_domain="providers",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload={
                "workspace_id": workspace_id,
                "provider_id": provider_id,
                "binding_id": selection.binding_id,
                "model_id": selection.model_id,
                "model_reasoning_effort": selection.model_reasoning_effort,
            },
        )
    return selection


def resolve_provider_for_runtime_session(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
) -> tuple[ProviderDefinition, ProviderSelection | None]:
    """Resolve the effective provider selection for one runtime session."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    execution_binding = session.execution_binding
    if execution_binding is not None:
        definition = active_registry.get_provider_definition(execution_binding.runtime_engine_id)
        selection = provider_selection_from_execution_binding(execution_binding)
        if definition.requires_credentials:
            binding = resolve_provider_binding(
                store,
                provider_id=definition.provider_id,
                workspace_id=session.workspace_id,
                binding_id=execution_binding.credential_binding_id,
            )
            if binding is None:
                raise ProviderSelectionError("credential_binding_unavailable")
        return definition, selection
    service = ProviderSelectionService(store, active_registry)
    return service.resolve_runtime_backend_provider(workspace_id=session.workspace_id)


def resolve_runtime_backend_for_session(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
) -> tuple[ProviderDefinition, ProviderSelection | None, RuntimeBackendAdapter]:
    """Resolve provider definition, selection, and executable runtime adapter for one session."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    definition, selection = resolve_provider_for_runtime_session(
        store,
        session=session,
        registry=active_registry,
        codex_command=codex_command,
    )
    return definition, selection, active_registry.get_runtime_adapter(definition.provider_id)


def resolve_provider_for_workspace(
    store: ProviderStore,
    *,
    workspace_id: str,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
) -> tuple[ProviderDefinition, ProviderSelection | None]:
    """Resolve the effective provider selection for one workspace."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    register_builtin_providers(store, registry=active_registry, codex_command=codex_command)
    service = ProviderSelectionService(store, active_registry)
    return service.resolve_runtime_backend_provider(workspace_id=workspace_id)


def resolve_workspace_provider_status(
    store: ProviderStore,
    *,
    workspace_id: str,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    refresh_model_catalog: bool = False,
) -> WorkspaceProviderStatus:
    """Return provider selection state without falling back to an implicit backend."""
    active_registry = effective_provider_registry(
        store,
        registry=registry,
        codex_command=codex_command,
        refresh_model_catalog=refresh_model_catalog,
    )
    available_providers = active_registry.list_provider_definitions()
    selection = store.get_provider_selection(workspace_id)
    if selection is None:
        return WorkspaceProviderStatus(
            workspace_id=workspace_id,
            configured=False,
            active_provider=None,
            selection=None,
            available_providers=available_providers,
            blocked_reason="no_provider_configured",
        )
    service = ProviderSelectionService(store, active_registry)
    try:
        definition, resolved_selection = service.resolve_runtime_backend_provider(workspace_id=workspace_id)
    except ProviderSelectionError as error:
        blocked_reason = "no_provider_configured" if str(error) == "no_provider_configured" else "provider_unavailable"
        return WorkspaceProviderStatus(
            workspace_id=workspace_id,
            configured=True,
            active_provider=None,
            selection=selection,
            available_providers=available_providers,
            blocked_reason=blocked_reason,
            blocked_detail=str(error),
        )
    except ProviderError as error:
        return WorkspaceProviderStatus(
            workspace_id=workspace_id,
            configured=True,
            active_provider=None,
            selection=selection,
            available_providers=available_providers,
            blocked_reason="provider_unavailable",
            blocked_detail=str(error),
        )
    return WorkspaceProviderStatus(
        workspace_id=workspace_id,
        configured=True,
        active_provider=definition,
        selection=resolved_selection,
        available_providers=available_providers,
    )


def read_workspace_provider_subscription_usage(
    store: ProviderStore,
    *,
    workspace_id: str,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    now: datetime | None = None,
) -> list[ProviderSubscriptionUsage]:
    """Read supported subscription limits for the active workspace provider."""
    active_registry = effective_provider_registry(
        store,
        registry=registry,
        codex_command=codex_command,
    )
    status = resolve_workspace_provider_status(
        store,
        workspace_id=workspace_id,
        registry=active_registry,
        codex_command=codex_command,
    )
    definition = status.active_provider
    if definition is None or not definition.capabilities.supports_subscription_usage:
        return []
    fetched_at = now or utcnow()
    try:
        adapter = active_registry.get_subscription_usage_adapter(definition.provider_id)
        usage = adapter.read_subscription_usage()
    except ProviderUsageUnavailableError as error:
        usage = ProviderSubscriptionUsage(
            provider_id=definition.provider_id,
            provider_label=definition.label,
            available=False,
            fetched_at=fetched_at,
            unavailable_reason=error.reason,
        )
    except ProviderError:
        usage = ProviderSubscriptionUsage(
            provider_id=definition.provider_id,
            provider_label=definition.label,
            available=False,
            fetched_at=fetched_at,
            unavailable_reason="provider_unavailable",
        )
    return [usage]


def build_resolved_runtime_backend_launch_spec(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    definition: ProviderDefinition,
    selection: ProviderSelection | None,
    runtime_adapter: RuntimeBackendAdapter,
    secret_store: SecretStore | None = None,
    observability_store=None,
) -> RuntimeBackendLaunchSpec:
    """Build a launch spec from an already resolved runtime backend."""
    secret_env: dict[str, str] = {}
    resolved_secret_refs: list[str] = []
    credential_binding_id: str | None = None
    if definition.requires_credentials:
        if secret_store is None:
            raise SecretBindingError(
                f"Provider `{definition.provider_id}` requires credentials but no secret store was provided for launch."
            )
        binding = resolve_provider_binding(
            store,
            provider_id=definition.provider_id,
            workspace_id=session.workspace_id,
            binding_id=None if selection is None else selection.binding_id,
        )
        if binding is None:
            raise SecretBindingError(f"Provider `{definition.provider_id}` has no active credential binding for runtime launch.")
        lease = resolve_secret_for_runtime(
            secret_store,
            context=SecretResolutionContext(
                workspace_id=session.workspace_id,
                provider_id=definition.provider_id,
                runtime_session_id=session.session_id,
                platform_delivery=True,
                allow_unbound_secret_refs=True,
            ),
            secret_ref=binding.secret_ref,
            observability_store=observability_store,
        )
        credential_binding_id = binding.binding_id
        resolved_secret_refs.append(lease.secret_ref)
        secret_env["MAVERICK_PROVIDER_SECRET"] = lease.value
    launch_kwargs = {
        "secret_env": secret_env,
        "credential_binding_id": credential_binding_id,
        "resolved_secret_refs": resolved_secret_refs,
    }
    launch_parameters = signature(runtime_adapter.build_launch_spec).parameters
    if "model_id" in launch_parameters:
        launch_kwargs["model_id"] = None if selection is None else selection.model_id
    if "model_reasoning_effort" in launch_parameters:
        launch_kwargs["model_reasoning_effort"] = None if selection is None else selection.model_reasoning_effort
    spec = runtime_adapter.build_launch_spec(session, **launch_kwargs)
    if observability_store is not None:
        record_platform_audit(
            observability_store,
            action="provider.launch_spec.build",
            status="succeeded",
            source_domain="providers",
            detail=f"Built runtime launch spec for provider `{definition.provider_id}`.",
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            provider_id=definition.provider_id,
            payload={
                "provider_id": definition.provider_id,
                "execution_mode": spec.execution_mode,
                "credential_binding_id": credential_binding_id,
                "resolved_secret_ref_count": len(resolved_secret_refs),
            },
        )
        record_platform_event(
            observability_store,
            event_type="provider.launch_spec.built",
            event_plane="runtime",
            source_domain="providers",
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            provider_id=definition.provider_id,
            payload={
                "provider_id": definition.provider_id,
                "execution_mode": spec.execution_mode,
                "credential_binding_id": credential_binding_id,
                "resolved_secret_ref_count": len(resolved_secret_refs),
            },
        )
    return spec


def build_runtime_backend_launch_spec(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
    secret_store: SecretStore | None = None,
    observability_store=None,
) -> RuntimeBackendLaunchSpec:
    """Build the launch spec for the selected provider for one runtime session."""
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    definition, selection = resolve_provider_for_runtime_session(
        store,
        session=session,
        registry=active_registry,
        codex_command=codex_command,
    )
    adapter = active_registry.get_runtime_adapter(definition.provider_id)
    return build_resolved_runtime_backend_launch_spec(
        store,
        session=session,
        definition=definition,
        selection=selection,
        runtime_adapter=adapter,
        secret_store=secret_store,
        observability_store=observability_store,
    )


def prepare_runtime_skills(
    store: ProviderStore,
    *,
    session: RuntimeSessionRecord,
    skills: list[SkillDefinition],
    runtime_adapter: RuntimeBackendAdapter | None = None,
    registry: ProviderRegistry | None = None,
    codex_command: str | None = None,
) -> list[SkillMaterialization]:
    """Prepare provider-specific runtime skill installation for one runtime session."""
    if runtime_adapter is not None:
        return runtime_adapter.prepare_runtime_skills(session, skills)
    active_registry = registry or builtin_provider_registry(codex_command=codex_command)
    definition, _selection = resolve_provider_for_runtime_session(
        store,
        session=session,
        registry=active_registry,
        codex_command=codex_command,
    )
    adapter = active_registry.get_runtime_adapter(definition.provider_id)
    return adapter.prepare_runtime_skills(session, skills)


__all__ = [
    "HostedModelProviderActivation",
    "activate_hosted_model_provider",
    "bind_provider_credential",
    "builtin_provider_registry",
    "build_resolved_runtime_backend_launch_spec",
    "build_runtime_backend_launch_spec",
    "configure_workspace_provider",
    "disable_provider_binding",
    "effective_provider_registry",
    "list_available_providers",
    "prepare_runtime_skills",
    "register_builtin_providers",
    "resolve_runtime_backend_for_session",
    "resolve_provider_for_workspace",
    "resolve_provider_for_runtime_session",
    "utcnow",
    "resolve_workspace_provider_status",
]
