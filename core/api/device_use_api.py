"""Authenticated browser activation surface for native macOS Device Use."""

from __future__ import annotations

import re

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import require_session
from core.device_use.errors import DeviceUseError


DEVICE_USE_ACTIVATIONS_PATH = "/api/device-use/activations"
_ACTIVATION_PATH = re.compile(r"^/api/device-use/activations/([0-9a-f-]{36})$")
_ACTIVATION_METRICS_PATH = re.compile(
    r"^/api/device-use/activations/([0-9a-f-]{36})/metrics$"
)


def handle_device_use_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes] | None:
    """Create, inspect, or revoke one current-user native activation."""
    path = str(environ.get("PATH_INFO") or "/")
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    match = _ACTIVATION_PATH.fullmatch(path)
    metrics_match = _ACTIVATION_METRICS_PATH.fullmatch(path)
    if path != DEVICE_USE_ACTIVATIONS_PATH and match is None and metrics_match is None:
        return None
    context = require_session(state, environ, start_response)
    if isinstance(context, list):
        return context
    service = state.device_use_service
    try:
        if path == DEVICE_USE_ACTIVATIONS_PATH and method == "POST":
            body = read_json_body(environ)
            generation = str(body.get("client_generation") or "").strip()
            if not generation or len(generation) > 100:
                return json_response(
                    start_response,
                    {"error": "device_use_client_generation_required"},
                    status="400 Bad Request",
                )
            activation, ticket = service.create_activation(
                owner_user_id=context.user.user_id,
                auth_session_id=context.session.session_id,
                workspace_id=context.workspace_id,
                session_generation=generation,
            )
            return json_response(
                start_response,
                {
                    **activation,
                    "ticket": ticket,
                    "websocket_path": "/ws/device-use/executor",
                },
                status="201 Created",
            )
        if match is not None and method == "GET":
            return json_response(
                start_response,
                service.public_activation(
                    match.group(1),
                    owner_user_id=context.user.user_id,
                    workspace_id=context.workspace_id,
                    auth_session_id=context.session.session_id,
                ),
            )
        if match is not None and method == "DELETE":
            service.stop_activation(
                match.group(1),
                owner_user_id=context.user.user_id,
                workspace_id=context.workspace_id,
                auth_session_id=context.session.session_id,
                reason="stopped_by_user",
            )
            return json_response(start_response, {"status": "stopped"})
        if metrics_match is not None and method == "GET":
            return json_response(
                start_response,
                service.activation_metrics(
                    metrics_match.group(1),
                    owner_user_id=context.user.user_id,
                    workspace_id=context.workspace_id,
                    auth_session_id=context.session.session_id,
                ),
            )
        return json_response(
            start_response,
            {"error": "method_not_allowed"},
            status="405 Method Not Allowed",
        )
    except DeviceUseError as error:
        status = (
            "403 Forbidden"
            if "forbidden" in error.reason_code or "ticket" in error.reason_code
            else "409 Conflict"
        )
        return json_response(start_response, {"error": error.reason_code}, status=status)
