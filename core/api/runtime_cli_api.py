"""Runtime-token authenticated Maverick CLI surface."""

from __future__ import annotations

from pathlib import Path

from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.platform_state import PlatformState
from core.app_sdk.cli import run_cli_json
from core.authorization.errors import AuthorizationError
from core.cli.models import CliInvocationContext
from core.identity.errors import UserNotFoundError
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.output_compaction.cli_result import (
    RUNTIME_CLI_OUTPUT_PROFILE_PROVIDER_COMPACT,
    compact_runtime_cli_result,
    runtime_cli_output_profile,
)
from core.runtime.workspace_api_token import RuntimeApiTokenClaims, validate_workspace_api_token_lifecycle
from core.workspaces.errors import WorkspaceMembershipError


def handle_runtime_cli_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Run official Maverick CLI commands for a workspace runtime session."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path != "/api/runtime/cli":
        return None
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")

    claims, auth_error = _runtime_claims(state, environ)
    if claims is None:
        return json_response(start_response, {"error": auth_error or "authentication_required"}, status="401 Unauthorized")

    body = read_json_body(environ)
    raw_argv = body.get("argv")
    if not isinstance(raw_argv, list) or not all(isinstance(token, str) for token in raw_argv):
        return json_response(start_response, {"error": "invalid_argv"}, status="400 Bad Request")
    output_profile, profile_error = runtime_cli_output_profile(body)
    if output_profile is None:
        return json_response(start_response, {"error": profile_error or "invalid_output_profile"}, status="400 Bad Request")

    try:
        session = state.runtime_store.get_session(str(claims["runtime_session_id"]))
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="401 Unauthorized")
    if session.workspace_id != str(claims["workspace_id"]) or session.status in {"stopped", "failed"}:
        return json_response(start_response, {"error": "runtime_session_not_active"}, status="401 Unauthorized")
    if session.effective_mode != claims.get("mode"):
        return json_response(start_response, {"error": "runtime_token_mismatch"}, status="401 Unauthorized")
    effective_mode = session.effective_mode
    caller_kind = "full_access_agent" if effective_mode == "full-access" else "sandbox_agent"
    try:
        platform_role, user_id, workspace_role = _runtime_actor_authority(state, session.owner_user_id, session.workspace_id)
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status="401 Unauthorized")
    trusted_argv = [*raw_argv, "--workspace", session.workspace_id]
    trusted_context = CliInvocationContext(
        caller_kind=caller_kind,
        workspace_id=session.workspace_id,
        agent_id=session.session_id,
        effective_mode=effective_mode,
        platform_role=platform_role,
        user_id=user_id,
        workspace_role=workspace_role,
        runtime_session_id=session.session_id,
    )
    try:
        result = run_cli_json(
            trusted_argv,
            state=state,
            repository_root=start_path,
            trusted_context=trusted_context,
        )
        if output_profile == RUNTIME_CLI_OUTPUT_PROFILE_PROVIDER_COMPACT:
            result = compact_runtime_cli_result(
                result,
                argv=trusted_argv,
                runtime_session_id=session.session_id,
            )
        result_status_code = result.get("status_code")
        response_status = status_line(result_status_code) if isinstance(result_status_code, int) and result_status_code >= 400 else "200 OK"
        return json_response(
            start_response,
            result,
            status=response_status,
        )
    except SystemExit as error:
        detail = str(error) or "CLI command failed."
        return _runtime_cli_error_response(
            start_response,
            detail=detail,
            output_profile=output_profile,
            argv=trusted_argv,
            runtime_session_id=session.session_id,
        )
    except Exception as error:
        return _runtime_cli_error_response(
            start_response,
            detail=str(error),
            output_profile=output_profile,
            argv=trusted_argv,
            runtime_session_id=session.session_id,
        )


def _runtime_claims(state: PlatformState, environ: dict) -> tuple[RuntimeApiTokenClaims | None, str | None]:
    header = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None, "authentication_required"
    return validate_workspace_api_token_lifecycle(state.runtime_store, token.strip())


def _runtime_actor_authority(state: PlatformState, user_id: str | None, workspace_id: str) -> tuple[str, str | None, str]:
    if not user_id:
        raise AuthorizationError("runtime_session_owner_not_authorized")
    try:
        user = state.identity_store.get_user(user_id)
    except UserNotFoundError:
        raise AuthorizationError("runtime_session_owner_not_authorized") from None
    try:
        membership = state.workspace_store.get_membership(user_id=user_id, workspace_id=workspace_id)
    except WorkspaceMembershipError:
        if user.platform_role == "admin":
            return user.platform_role, user_id, "admin"
        raise AuthorizationError("runtime_session_owner_not_authorized") from None
    if membership.status != "active" and user.platform_role != "admin":
        raise AuthorizationError("runtime_session_owner_not_authorized")
    workspace_role = membership.role if membership.status == "active" else "admin"
    return user.platform_role, user_id, workspace_role


def _runtime_cli_error_response(
    start_response: StartResponse,
    *,
    detail: str,
    output_profile: str,
    argv: list[str],
    runtime_session_id: str,
) -> list[bytes]:
    result = {"status_code": 400, "error": "cli_command_failed", "detail": detail}
    if output_profile == RUNTIME_CLI_OUTPUT_PROFILE_PROVIDER_COMPACT:
        result = compact_runtime_cli_result(
            result,
            argv=argv,
            runtime_session_id=runtime_session_id,
        )
    return json_response(start_response, result, status="400 Bad Request")
