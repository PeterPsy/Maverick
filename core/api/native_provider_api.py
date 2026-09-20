"""Human-admin activation of a reviewed native provider connection."""

from core.api.http import StartResponse, json_response, read_json_body
from core.api.session_api import RequestSession
from core.providers.errors import ProviderError
from core.providers.payloads import provider_payload
from core.providers.service import activate_native_agent_provider


def activate_native_provider(state, context: RequestSession, environ, start_response: StartResponse):
    """Use the same runtime validation as operator CLI activation."""
    if environ.get("REQUEST_METHOD", "GET").upper() != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if context.user.platform_role != "admin":
        return json_response(start_response, {"error": "admin_required"}, status="403 Forbidden")
    body = read_json_body(environ)
    if body.get("confirmation") != "native-runtime-reviewed":
        return json_response(
            start_response, {"error": "native_activation_confirmation_required"}, status="400 Bad Request",
        )
    provider_id = body.get("provider_id")
    if not isinstance(provider_id, str) or not provider_id.strip():
        return json_response(start_response, {"error": "provider_id_required"}, status="400 Bad Request")
    try:
        activation = activate_native_agent_provider(
            state.provider_store,
            provider_id=provider_id.strip(),
            registry=state.provider_registry,
            observability_store=state.observability_store,
        )
    except ProviderError as error:
        return json_response(start_response, {"error": str(error)}, status="400 Bad Request")
    return json_response(start_response, {
        "provider": provider_payload(activation.definition),
        "profile_count": activation.profile_count,
    })
