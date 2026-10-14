"""MCP entrypoint for `github-actions`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import GitHubActionsError, handle_action, reference_manifest

payload = read_entrypoint_payload()
tool_name = str(payload.raw.get("tool_name") or "")
if tool_name == "github_actions_reference_manifest":
    emit_json(
        {
            "app_id": payload.app_id or "github-actions",
            "workspace_id": payload.workspace_id,
            "tool_name": tool_name,
            **reference_manifest(),
        }
    )
    raise SystemExit(0)

arguments = dict(payload.arguments)
arguments.setdefault("action", "manifest")
try:
    result = handle_action(
        arguments,
        app_secrets=dict(payload.raw.get("app_secrets") or {}),
        app_secret_errors=list(payload.raw.get("app_secret_errors") or []),
    )
except GitHubActionsError as error:
    result = {"ok": False, "error": "github_actions_error", "detail": str(error)}

result.update(
    {
        "app_id": payload.app_id or "github-actions",
        "workspace_id": payload.workspace_id,
        "tool_name": tool_name,
    }
)
emit_json(result)
