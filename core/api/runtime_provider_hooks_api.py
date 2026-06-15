"""Runtime-token authenticated provider hook bridge."""

from __future__ import annotations

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.output_compaction.provider_hooks import build_codex_post_tool_use_response
from core.runtime.workspace_api_token import RuntimeApiTokenClaims, validate_workspace_api_token_lifecycle


CODEX_POST_TOOL_USE_HOOK_PATH = "/api/runtime/provider-hooks/codex/post-tool-use"


def handle_runtime_provider_hooks_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes] | None:
    """Handle provider-owned hook callbacks from a runtime session."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path != CODEX_POST_TOOL_USE_HOOK_PATH:
        return None
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")

    claims, auth_error = _runtime_claims(state, environ)
    if claims is None:
        return json_response(start_response, {"error": auth_error or "authentication_required"}, status="401 Unauthorized")

    try:
        session = state.runtime_store.get_session(str(claims["runtime_session_id"]))
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="401 Unauthorized")
    if session.workspace_id != str(claims["workspace_id"]) or session.status in {"stopped", "failed"}:
        return json_response(start_response, {"error": "runtime_session_not_active"}, status="401 Unauthorized")
    if session.effective_mode != claims.get("mode"):
        return json_response(start_response, {"error": "runtime_token_mismatch"}, status="401 Unauthorized")

    body = read_json_body(environ)
    result = build_codex_post_tool_use_response(
        body,
        runtime_session_id=session.session_id,
    )
    return json_response(start_response, result)


def _runtime_claims(state: PlatformState, environ: dict) -> tuple[RuntimeApiTokenClaims | None, str | None]:
    header = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None, "authentication_required"
    return validate_workspace_api_token_lifecycle(state.runtime_store, token.strip())
