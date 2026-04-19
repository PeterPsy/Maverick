"""Generic workspace file HTTP API."""

from __future__ import annotations

import binascii

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.workspaces.file_uploads import save_workspace_upload


def handle_workspace_files_api(state: PlatformState, environ: dict, start_response: StartResponse, *, start_path) -> list[bytes] | None:
    """Handle workspace-owned file upload routes."""
    path = environ.get("PATH_INFO", "/")
    if path != "/api/workspace-files/uploads":
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    body = read_json_body(environ)
    filename = str(body.get("filename") or "").strip()
    content_base64 = str(body.get("content_base64") or "").strip()
    if not filename or not content_base64:
        return json_response(start_response, {"error": "missing_upload_payload"}, status="400 Bad Request")
    try:
        uploaded = save_workspace_upload(
            workspace_id=context.workspace_id,
            filename=filename,
            content_type=str(body.get("content_type") or "").strip(),
            content_base64=content_base64,
            start_path=start_path,
        )
    except (ValueError, binascii.Error):
        return json_response(start_response, {"error": "invalid_base64_payload"}, status="400 Bad Request")
    return json_response(start_response, {"file": uploaded.as_payload()}, status="201 Created")
