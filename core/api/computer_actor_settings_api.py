"""Authenticated workspace configuration for the PC use operator."""

from core.api.http import json_response, read_json_body
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_provider_selection_authority
from core.providers.computer_actor_settings import configure_computer_actor, computer_actor_settings_payload
from core.providers.errors import ProviderSelectionError


def computer_actor_settings(state, context):
    allowed = True
    try:
        require_provider_selection_authority(state.workspace_store, user=context.user, workspace_id=context.workspace_id)
    except AuthorizationError:
        allowed = False
    return computer_actor_settings_payload(state.provider_store, context.workspace_id, can_configure=allowed)


def handle_computer_actor_settings(state, context, environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if method == "GET":
        return json_response(start_response, computer_actor_settings(state, context))
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    try:
        require_provider_selection_authority(state.workspace_store, user=context.user, workspace_id=context.workspace_id)
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    body = read_json_body(environ)
    if (not isinstance(body, dict) or set(body) - {"workspace_id", "provider_id", "model_id", "reasoning_effort"}
        or body.get("workspace_id") != context.workspace_id
        or not all(isinstance(body.get(key), str) and body[key].strip() for key in ("provider_id", "model_id"))
        or (body.get("reasoning_effort") is not None and not isinstance(body["reasoning_effort"], str))):
        return json_response(start_response, {"error": "computer_use_selection_invalid"}, status="400 Bad Request")
    try:
        configure_computer_actor(state.provider_store, workspace_id=context.workspace_id,
            provider_id=body["provider_id"].strip(), model_id=body["model_id"].strip(),
            reasoning_effort=(body.get("reasoning_effort") or "").strip() or None)
    except ProviderSelectionError as error:
        return json_response(start_response, {"error": str(error)}, status="400 Bad Request")
    return json_response(start_response, computer_actor_settings(state, context))
