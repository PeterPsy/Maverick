"""Provider and runtime-status HTTP API for the hosted platform shell."""

from __future__ import annotations

from dataclasses import asdict

from core.api.http import StartResponse, json_response
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.providers.models import ProviderDefinition, ProviderSelection
from core.providers.service import list_available_providers, resolve_provider_for_workspace
from core.runtime.runtime_session import RuntimeSessionRecord


def provider_payload(definition: ProviderDefinition) -> dict[str, object]:
    """Return public provider metadata."""
    return {
        "provider_id": definition.provider_id,
        "label": definition.label,
        "description": definition.description,
        "kind": definition.kind,
        "status": definition.status,
        "capabilities": asdict(definition.capabilities),
        "default_model_family": definition.default_model_family,
        "requires_credentials": definition.requires_credentials,
        "supported_execution_modes": list(definition.supported_execution_modes),
    }


def provider_selection_payload(selection: ProviderSelection | None) -> dict[str, object] | None:
    """Return public provider-selection metadata."""
    if selection is None:
        return None
    return {
        "workspace_id": selection.workspace_id,
        "provider_id": selection.provider_id,
        "binding_id": selection.binding_id,
        "selection_scope": selection.selection_scope,
        "selection_reason": selection.selection_reason,
        "updated_at": selection.updated_at,
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
        "started_at": session.started_at,
        "updated_at": session.updated_at,
        "ended_at": session.ended_at,
        "last_progress_at": session.last_progress_at,
    }


def workspace_provider_status(state: PlatformState, *, workspace_id: str) -> dict[str, object]:
    """Return the active provider state for one workspace."""
    definition, selection = resolve_provider_for_workspace(state.provider_store, workspace_id=workspace_id)
    return {
        "workspace_id": workspace_id,
        "active_provider": provider_payload(definition),
        "selection": provider_selection_payload(selection),
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


def handle_provider_api(state: PlatformState, environ: dict, start_response: StartResponse) -> list[bytes] | None:
    """Handle provider and runtime routes."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path not in {"/api/providers", "/api/providers/active", "/api/runtime/status"}:
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    if method != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if path == "/api/providers":
        return json_response(
            start_response,
            {
                "items": [provider_payload(provider) for provider in list_available_providers(state.provider_store)],
                **workspace_provider_status(state, workspace_id=context.workspace_id),
            },
        )
    if path == "/api/providers/active":
        return json_response(start_response, workspace_provider_status(state, workspace_id=context.workspace_id))
    if path == "/api/runtime/status":
        return json_response(start_response, workspace_runtime_status(state, workspace_id=context.workspace_id))
    return None
