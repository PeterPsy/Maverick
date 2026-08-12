"""Provider and runtime-status HTTP API for the hosted platform shell."""

from __future__ import annotations

from dataclasses import replace

from core.api.http import StartResponse, json_response, query_params
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_provider_selection_authority
from core.providers.models import ProviderDefinition, ProviderHostedSelection, ProviderSelection, ProviderSpeechSelection
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
from core.providers.provider_authorization import check_provider_credential_authorization
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import (
    activate_hosted_model_provider,
    activate_speech_provider,
    configure_hosted_model_provider,
    configure_speech_provider,
    configure_workspace_provider,
    effective_provider_registry,
    read_workspace_provider_subscription_usage,
    resolve_workspace_provider_status,
)
from core.runtime.runtime_session import RuntimeSessionRecord


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
    if not selected_reasoning and model_option is not None:
        selected_reasoning = model_option.default_reasoning_effort
    return {
        "selected_model_id": selected_model_id,
        "selected_reasoning_effort": selected_reasoning,
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


def workspace_hosted_text_status(state: PlatformState, *, workspace_id: str) -> dict[str, object]:
    """Return workspace-scoped hosted text provider status without secret refs."""
    registry = effective_provider_registry(state.provider_store)
    available_providers = [
        provider
        for provider in registry.list_provider_definitions()
        if provider.provider_role == "model_provider"
        and provider.execution_contract is not None
        and provider.execution_contract.adapter_type == "hosted_text_generation"
    ]
    get_hosted_selection = getattr(state.provider_store, "get_hosted_provider_selection", None)
    selection = (
        get_hosted_selection(workspace_id=workspace_id, profile="fast_model")
        if callable(get_hosted_selection)
        else None
    )
    decision = select_provider_for_profile(
        "fast_model",
        ProviderRoutingContext(
            workspace_id=workspace_id,
            provider_store=state.provider_store,
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
    display_providers = [
        _hosted_provider_display_definition(state, provider, workspace_id=workspace_id)
        for provider in available_providers
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
        "available_providers": [provider_payload(provider) for provider in sort_provider_definitions(display_providers)],
        "route_preview": routing_decision_payload(decision),
    }


def _hosted_provider_display_definition(
    state: PlatformState,
    provider: ProviderDefinition,
    *,
    workspace_id: str,
) -> ProviderDefinition:
    if provider.status == "active":
        return provider
    authorization = check_provider_credential_authorization(
        state.provider_store,
        definition=provider,
        workspace_id=workspace_id,
        secret_store=getattr(state, "secret_store", None),
    )
    if not authorization.authorized:
        return provider
    return replace(provider, status="active")


def workspace_speech_stt_status(state: PlatformState, *, workspace_id: str) -> dict[str, object]:
    """Return workspace-scoped speech-to-text provider status without secret refs."""
    registry = effective_provider_registry(state.provider_store)
    available_providers = [
        provider
        for provider in registry.list_provider_definitions()
        if provider.provider_role == "speech_provider"
        and "audio" in provider.capabilities.input_modalities
        and "text" in provider.capabilities.output_modalities
    ]
    get_speech_selection = getattr(state.provider_store, "get_speech_provider_selection", None)
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
                state.provider_store,
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
            state.provider_store,
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


def runtime_session_payload(session: RuntimeSessionRecord) -> dict[str, object]:
    """Return public runtime session metadata."""
    return {
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
    }


def workspace_provider_status(
    state: PlatformState,
    *,
    workspace_id: str,
    refresh_model_catalog: bool = False,
) -> dict[str, object]:
    """Return the active provider state for one workspace."""
    status = resolve_workspace_provider_status(
        state.provider_store,
        workspace_id=workspace_id,
        refresh_model_catalog=refresh_model_catalog,
    )
    active_provider = None if status.active_provider is None else provider_payload(status.active_provider)
    return {
        "workspace_id": workspace_id,
        "configured": status.configured,
        "active_provider": active_provider,
        "selection": provider_selection_payload(status.selection),
        "model_settings": None if status.active_provider is None else provider_model_settings_payload(status.active_provider, status.selection),
        "hosted_text": workspace_hosted_text_status(state, workspace_id=workspace_id),
        "speech_stt": workspace_speech_stt_status(state, workspace_id=workspace_id),
        "blocked_reason": status.blocked_reason,
        "blocked_detail": status.blocked_detail,
        "available_providers": [provider_payload(provider) for provider in sort_provider_definitions(status.available_providers)],
    }


def workspace_runtime_status(state: PlatformState, *, workspace_id: str) -> dict[str, object]:
    """Return runtime status for one workspace."""
    return {
        **workspace_provider_status(state, workspace_id=workspace_id),
        "sessions": [
            runtime_session_payload(session)
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
        "/api/runtime/status",
    }:
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
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
                observability_store=state.observability_store,
            )
        except Exception as error:
            return json_response(start_response, {"error": str(error)}, status="400 Bad Request")
        return json_response(start_response, workspace_provider_status(state, workspace_id=context.workspace_id))
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
                observability_store=state.observability_store,
            )
        except Exception as error:
            return json_response(start_response, {"error": str(error)}, status="400 Bad Request")
        return json_response(start_response, workspace_provider_status(state, workspace_id=context.workspace_id))
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
            configure_workspace_provider(
                state.provider_store,
                workspace_id=context.workspace_id,
                provider_id=provider_id,
                model_id=model_id,
                model_reasoning_effort=model_reasoning_effort,
                observability_store=state.observability_store,
            )
        except Exception as error:
            return json_response(start_response, {"error": str(error)}, status="400 Bad Request")
        return json_response(start_response, workspace_provider_status(state, workspace_id=context.workspace_id))
    if method != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if path == "/api/providers/usage":
        if getattr(context.user, "platform_role", None) != "admin":
            return json_response(start_response, {"error": "provider_usage_forbidden"}, status="403 Forbidden")
        usages = read_workspace_provider_subscription_usage(
            state.provider_store,
            workspace_id=context.workspace_id,
        )
        return json_response(
            start_response,
            {
                "workspace_id": context.workspace_id,
                "items": [provider_subscription_usage_payload(usage) for usage in usages],
            },
        )
    if path == "/api/providers":
        provider_status = workspace_provider_status(state, workspace_id=context.workspace_id, refresh_model_catalog=True)
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
                registry=effective_provider_registry(state.provider_store),
                secret_store=state.secret_store,
                request_id=params.get("request_id"),
                user_tier=params.get("user_tier"),
                app_id=params.get("app_id"),
                allow_fallback_codex=str(params.get("allow_fallback_codex") or "").lower() in {"1", "true", "yes"},
            ),
        )
        return json_response(start_response, {"decision": routing_decision_payload(decision)})
    if path == "/api/providers/active":
        return json_response(start_response, workspace_provider_status(state, workspace_id=context.workspace_id))
    if path == "/api/runtime/status":
        return json_response(start_response, workspace_runtime_status(state, workspace_id=context.workspace_id))
    return None
