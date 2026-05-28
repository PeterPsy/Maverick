"""MCP entrypoint for the Calendar app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, mcp_result_for_tool, secret_lookup_for_remote_mutation


payload = read_entrypoint_payload()
local_app_id = payload.app_id or "calendar"
tool_name = str(payload.raw.get("tool_name") or "")
arguments = dict(payload.arguments)
if payload.raw.get("surface") == "secret_selector":
    action_by_tool = {
        "calendar_create_event": "create",
        "calendar_update_event": "update",
        "calendar_delete_event": "delete",
        "calendar_move_event": "move",
    }
    if tool_name in action_by_tool:
        arguments.setdefault("action", action_by_tool[tool_name])
    emit_json(secret_lookup_for_remote_mutation(Path(payload.data_root), arguments))
    raise SystemExit(0)
status_code, result = mcp_result_for_tool(
    Path(payload.data_root),
    tool_name,
    arguments,
    app_id=local_app_id,
    workspace_id=payload.workspace_id,
    app_secrets=dict(payload.raw.get("app_secrets") or {}),
    app_secret_errors=list(payload.raw.get("app_secret_errors") or []),
)
result.update({"app_id": local_app_id, "workspace_id": payload.workspace_id, "tool_name": tool_name, "status_code": status_code})
if status_code < 400 and not result.get("idempotent_replay"):
    result["app_events"] = app_events_for_action(str(arguments.get("action") or result.get("action") or "list"), app_id=local_app_id)
emit_json(result)
