"""MCP entrypoint for the Calendar app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, mcp_result_for_tool


payload = read_entrypoint_payload()
local_app_id = payload.app_id or "calendar"
tool_name = str(payload.raw.get("tool_name") or "")
arguments = dict(payload.arguments)
status_code, result = mcp_result_for_tool(
    Path(payload.data_root),
    tool_name,
    arguments,
    app_id=local_app_id,
    workspace_id=payload.workspace_id,
)
result.update({"app_id": local_app_id, "workspace_id": payload.workspace_id, "tool_name": tool_name, "status_code": status_code})
if status_code < 400 and not result.get("idempotent_replay"):
    result["app_events"] = app_events_for_action(str(arguments.get("action") or result.get("action") or "list"), app_id=local_app_id)
emit_json(result)
