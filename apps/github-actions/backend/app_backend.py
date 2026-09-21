"""Authenticated workspace-admin backend for GitHub Actions operations."""

from __future__ import annotations

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

from service import GitHubActionsError, handle_action


payload = read_entrypoint_payload()
try:
    result = handle_action(
        dict(payload.body),
        app_secrets=dict(payload.raw.get("app_secrets") or {}),
        app_secret_errors=list(payload.raw.get("app_secret_errors") or []),
    )
    status_code = 200 if result.get("ok", True) else 400
except GitHubActionsError as error:
    status_code = 502
    result = {"ok": False, "error": "github_actions_error", "detail": str(error)}

result.update({"app_id": payload.app_id or "github-actions", "workspace_id": payload.workspace_id})
emit_json(backend_response(status_code, result))
