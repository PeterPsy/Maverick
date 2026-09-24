import base64
import re
from uuid import uuid4

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import require_session
from core.device_use.contract import device_use_dynamic_tools
from core.device_use.errors import DeviceUseError
from core.device_use.runtime_registry import device_use_service_for_session
from core.runtime.workspace_api_token import validate_workspace_api_token_lifecycle


DEVICE_USE_ACTIVATIONS_PATH = "/api/device-use/activations"
DEVICE_USE_TOOLS_PATH = "/api/device-use/tools"
DEVICE_USE_INVOKE_PATH = "/api/device-use/invoke"
DEVICE_USE_END_TURN_PATH = "/api/device-use/end-turn"
_ACTIVATION_PATH = re.compile(r"^/api/device-use/activations/([0-9a-f-]{36})$")
_ACTIVATION_METRICS_PATH = re.compile(
    r"^/api/device-use/activations/([0-9a-f-]{36})/metrics$"
)


def _authenticate_device_use_caller(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
) -> tuple[str | None, str, object | None] | list[bytes]:
    """Resolve (runtime_session_id, workspace_id, binding) via Bearer token or user session."""
    auth_header = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    if auth_header:
        scheme, separator, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token:
            claims, auth_error = validate_workspace_api_token_lifecycle(
                state.runtime_store, token.strip()
            )
            if auth_error or claims is None:
                return json_response(
                    start_response,
                    {"error": auth_error or "authentication_required"},
                    status="401 Unauthorized",
                )
            session_id = str(claims["runtime_session_id"])
            workspace_id = str(claims["workspace_id"])
            binding = None
            try:
                session = state.runtime_store.get_session(session_id)
                binding = getattr(session, "device_use_binding", None)
            except Exception:
                binding = None
            return session_id, workspace_id, binding

    context = require_session(state, environ, start_response)
    if isinstance(context, list):
        return context
    session_id = str(environ.get("HTTP_X_MAVERICK_SESSION_ID") or "").strip() or None
    binding = None
    if session_id:
        try:
            session = state.runtime_store.get_session(session_id)
            binding = getattr(session, "device_use_binding", None)
        except Exception:
            binding = None
    return session_id, context.workspace_id, binding


def handle_device_use_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes] | None:
    """Create, inspect, invoke, or revoke native macOS Device Use actions."""
    path = str(environ.get("PATH_INFO") or "/")
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    match = _ACTIVATION_PATH.fullmatch(path)
    metrics_match = _ACTIVATION_METRICS_PATH.fullmatch(path)
    if (
        path != DEVICE_USE_ACTIVATIONS_PATH
        and path != DEVICE_USE_TOOLS_PATH
        and path != DEVICE_USE_INVOKE_PATH
        and path != DEVICE_USE_END_TURN_PATH
        and match is None
        and metrics_match is None
    ):
        return None

    if path == DEVICE_USE_TOOLS_PATH:
        if method != "GET":
            return json_response(
                start_response,
                {"error": "method_not_allowed"},
                status="405 Method Not Allowed",
            )
        auth = _authenticate_device_use_caller(state, environ, start_response)
        if isinstance(auth, list):
            return auth
        tools = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            }
            for tool in device_use_dynamic_tools()
        ]
        return json_response(start_response, {"tools": tools})

    if path == DEVICE_USE_INVOKE_PATH:
        if method != "POST":
            return json_response(
                start_response,
                {"error": "method_not_allowed"},
                status="405 Method Not Allowed",
            )
        auth = _authenticate_device_use_caller(state, environ, start_response)
        if isinstance(auth, list):
            return auth
        session_id, workspace_id, binding = auth
        body = read_json_body(environ)
        if not session_id:
            session_id = str(body.get("session_id") or "").strip() or None
            if session_id:
                try:
                    session = state.runtime_store.get_session(session_id)
                    binding = getattr(session, "device_use_binding", None)
                except Exception:
                    binding = None
        if not session_id or binding is None:
            return json_response(
                start_response,
                {"error": "device_use_session_binding_required"},
                status="403 Forbidden",
            )
        service = device_use_service_for_session(session_id) or state.device_use_service
        if service is None:
            return json_response(
                start_response,
                {"error": "device_use_service_unavailable"},
                status="503 Service Unavailable",
            )
        tool_name = str(body.get("tool") or body.get("name") or "").strip()
        arguments = body.get("arguments")
        if not isinstance(arguments, dict):
            return json_response(
                start_response,
                {"error": "device_use_arguments_invalid"},
                status="400 Bad Request",
            )

        state_rec = None
        try:
            state_rec = state.runtime_store.get_state(session_id)
        except Exception:
            pass

        turn_id = str(
            body.get("turn_id")
            or (state_rec.current_turn_id if state_rec and state_rec.current_turn_id else "")
        ).strip()
        if not turn_id:
            turn_id = f"turn_{session_id[-8:]}"

        task_text = str(body.get("task_text") or "").strip()
        if not task_text and state_rec and state_rec.current_turn_id:
            try:
                turn = state.runtime_store.get_turn(state_rec.current_turn_id)
                task_text = turn.input_text
            except Exception:
                pass

        provider_thread_id = str(body.get("provider_thread_id") or "").strip()
        if not provider_thread_id:
            try:
                pstate = state.runtime_store.get_provider_state(session_id)
                provider_thread_id = pstate.provider_thread_id or session_id
            except Exception:
                provider_thread_id = session_id

        provider_turn_id = str(body.get("provider_turn_id") or turn_id).strip()
        call_id = str(body.get("call_id") or f"call_{uuid4().hex[:12]}").strip()

        try:
            invoke_result = service.invoke(
                binding=binding,
                runtime_session_id=session_id,
                turn_id=turn_id,
                provider_thread_id=provider_thread_id,
                provider_turn_id=provider_turn_id,
                call_id=call_id,
                tool_name=tool_name,
                arguments=arguments,
                task_text=task_text,
            )
            image_b64 = None
            if invoke_result.image_jpeg is not None:
                image_b64 = base64.b64encode(invoke_result.image_jpeg).decode("ascii")
            return json_response(
                start_response,
                {
                    "invocation_id": invoke_result.invocation_id,
                    "call_id": invoke_result.call_id,
                    "result": invoke_result.result,
                    "image_base64": image_b64,
                    "native_duration_ms": invoke_result.native_duration_ms,
                    "is_error": invoke_result.result.get("success") is False,
                },
            )
        except DeviceUseError as error:
            return json_response(
                start_response,
                {
                    "error": error.reason_code,
                    "is_error": True,
                    "result": {
                        "success": False,
                        "contentItems": [{"type": "inputText", "text": error.reason_code}],
                    },
                },
            )
        except Exception as error:
            service.stop_activation(
                binding.activation_id, reason="device_use_execution_unknown"
            )
            return json_response(
                start_response,
                {
                    "error": "device_use_execution_unknown",
                    "is_error": True,
                    "result": {
                        "success": False,
                        "contentItems": [
                            {"type": "inputText", "text": "device_use_execution_unknown"}
                        ],
                    },
                },
            )

    if path == DEVICE_USE_END_TURN_PATH:
        if method != "POST":
            return json_response(
                start_response,
                {"error": "method_not_allowed"},
                status="405 Method Not Allowed",
            )
        auth = _authenticate_device_use_caller(state, environ, start_response)
        if isinstance(auth, list):
            return auth
        session_id, workspace_id, binding = auth
        body = read_json_body(environ)
        if not session_id:
            session_id = str(body.get("session_id") or "").strip() or None
            if session_id:
                try:
                    session = state.runtime_store.get_session(session_id)
                    binding = getattr(session, "device_use_binding", None)
                except Exception:
                    binding = None
        if not session_id or binding is None:
            return json_response(
                start_response,
                {"error": "device_use_session_binding_required"},
                status="403 Forbidden",
            )
        service = device_use_service_for_session(session_id) or state.device_use_service
        turn_id = str(body.get("turn_id") or "").strip()
        if not turn_id:
            try:
                state_rec = state.runtime_store.get_state(session_id)
                turn_id = state_rec.current_turn_id or ""
            except Exception:
                turn_id = ""
        if turn_id:
            try:
                service.end_turn(binding, runtime_session_id=session_id, turn_id=turn_id)
            except DeviceUseError:
                pass
        return json_response(start_response, {"status": "ok"})

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
