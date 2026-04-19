"""Settings and recovery HTTP API for the hosted platform shell."""

from __future__ import annotations

from dataclasses import asdict, replace

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.provider_api import workspace_provider_status, workspace_runtime_status
from core.api.session_api import RequestSession, public_user_payload, require_session
from core.api.workspace_api import workspace_payload
from core.providers.service import builtin_provider_registry
from core.recovery.service import execute_session_restart, record_provider_health, record_runtime_health, recovery_status
from core.runtime.errors import RuntimeSessionNotFoundError


GOVERNANCE_PATCH_FIELDS = {
    "allow_app_installation",
    "allow_agent_creation",
    "allow_agent_management",
    "allow_custom_apps",
    "allow_full_access_runtime",
}


def platform_settings_payload(state: PlatformState, context: RequestSession) -> dict[str, object]:
    """Return shell-visible platform settings without secrets."""
    return {
        "user": public_user_payload(context.user),
        "workspace": workspace_payload(state, context.workspace_id),
        "provider": workspace_provider_status(state, workspace_id=context.workspace_id),
        "runtime": workspace_runtime_status(state, workspace_id=context.workspace_id),
        "recovery": recovery_status(state.recovery_store, workspace_id=context.workspace_id),
    }


def _patch_workspace_governance(state: PlatformState, context: RequestSession, body: dict) -> dict[str, object]:
    if context.user.platform_role != "admin":
        return {"error": "admin_required"}
    governance = state.workspace_store.get_governance(context.workspace_id)
    patch = {
        key: bool(body[key])
        for key in GOVERNANCE_PATCH_FIELDS
        if key in body
    }
    updated = replace(governance, **patch) if patch else governance
    saved = state.workspace_store.save_governance(updated)
    return {"workspace_id": context.workspace_id, "governance": asdict(saved)}


def _record_workspace_health(state: PlatformState, context: RequestSession, body: dict) -> dict[str, object]:
    target_kind = str(body.get("target_kind") or "provider")
    if target_kind == "runtime":
        session_id = str(body.get("session_id") or "")
        try:
            session = state.runtime_store.get_session(session_id)
        except RuntimeSessionNotFoundError:
            return {"error": "runtime_session_not_found"}
        return {"result": asdict(record_runtime_health(state.recovery_store, session=session))}
    provider_id = str(body.get("provider_id") or "")
    if not provider_id:
        provider_id = workspace_provider_status(state, workspace_id=context.workspace_id)["active_provider"]["provider_id"]
    result = record_provider_health(
        state.recovery_store,
        provider_registry=builtin_provider_registry(),
        provider_id=provider_id,
        workspace_id=context.workspace_id,
        observability_store=state.observability_store,
    )
    return {"result": asdict(result)}


def handle_settings_api(state: PlatformState, environ: dict, start_response: StartResponse) -> list[bytes] | None:
    """Handle platform settings and recovery routes."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    owned_paths = {
        "/api/settings/platform",
        "/api/settings/workspace",
        "/api/recovery/status",
        "/api/recovery/health",
        "/api/recovery/restart-runtime",
    }
    if path not in owned_paths:
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response

    if path == "/api/settings/platform" and method == "GET":
        return json_response(start_response, platform_settings_payload(state, context))
    if path == "/api/settings/workspace" and method == "PATCH":
        payload = _patch_workspace_governance(state, context, read_json_body(environ))
        status = "403 Forbidden" if "error" in payload else "200 OK"
        return json_response(start_response, payload, status=status)
    if path == "/api/recovery/status" and method == "GET":
        return json_response(start_response, recovery_status(state.recovery_store, workspace_id=context.workspace_id))
    if path == "/api/recovery/health" and method == "POST":
        payload = _record_workspace_health(state, context, read_json_body(environ))
        status = "404 Not Found" if "error" in payload else "200 OK"
        return json_response(start_response, payload, status=status)
    if path == "/api/recovery/restart-runtime" and method == "POST":
        body = read_json_body(environ)
        session_id = str(body.get("session_id") or "")
        try:
            intent, session = execute_session_restart(
                state.recovery_store,
                runtime_store=state.runtime_store,
                session_id=session_id,
                reason=str(body.get("reason") or "operator requested restart"),
                observability_store=state.observability_store,
            )
        except RuntimeSessionNotFoundError:
            return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
        return json_response(start_response, {"intent": asdict(intent), "session": asdict(session)})

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
