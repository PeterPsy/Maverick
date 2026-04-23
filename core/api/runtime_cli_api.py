"""Runtime-token authenticated Maverick CLI surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.app_sdk.cli import run_cli_json
from core.runtime.workspace_api_token import verify_workspace_api_token


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

    claims = _runtime_claims(environ)
    if claims is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")

    body = read_json_body(environ)
    raw_argv = body.get("argv")
    if not isinstance(raw_argv, list) or not all(isinstance(token, str) for token in raw_argv):
        return json_response(start_response, {"error": "invalid_argv"}, status="400 Bad Request")

    effective_mode = _effective_mode(body)
    caller_kind = "full_access_agent" if effective_mode == "full-access" else "sandbox_agent"
    trusted_argv = [
        *raw_argv,
        "--workspace",
        claims["workspace_id"],
        "--caller-kind",
        caller_kind,
        "--effective-mode",
        effective_mode,
        "--agent-id",
        claims["runtime_session_id"],
        "--platform-role",
        "member",
    ]
    try:
        return json_response(start_response, run_cli_json(trusted_argv, state=state, repository_root=start_path))
    except SystemExit as error:
        detail = str(error) or "CLI command failed."
        return json_response(start_response, {"error": "cli_command_failed", "detail": detail}, status="400 Bad Request")
    except Exception as error:
        return json_response(start_response, {"error": "cli_command_failed", "detail": str(error)}, status="400 Bad Request")


def _runtime_claims(environ: dict) -> dict[str, str] | None:
    header = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    return verify_workspace_api_token(token.strip())


def _effective_mode(body: dict[str, Any]) -> str:
    mode = str(body.get("effective_mode") or "").strip()
    return "full-access" if mode == "full-access" else "sandbox"
