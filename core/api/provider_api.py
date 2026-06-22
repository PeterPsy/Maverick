"""Provider and runtime-status HTTP API for the hosted platform shell."""

from __future__ import annotations

from core.api.http import StartResponse, json_response, query_params
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_provider_selection_authority
from core.providers.models import ProviderDefinition, ProviderSelection
from core.providers.payloads import (
    provider_model_option_payload,
    provider_payload,
    provider_selection_payload,
    routing_decision_payload,
    sort_provider_definitions,
)
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import (
    activate_hosted_model_provider,
    configure_workspace_provider,
    effective_provider_registry,
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
    if path not in {"/api/providers", "/api/providers/active", "/api/providers/hosted/active", "/api/providers/route", "/api/runtime/status"}:
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
                "preflight": routing_decision_payload(activation.routing_decision),
            },
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
