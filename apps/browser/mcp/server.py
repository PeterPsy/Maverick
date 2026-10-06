"""MCP entrypoint for the Browser app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, mcp_result_for_tool
from models import MCP_TOOL_ACTIONS


payload = read_entrypoint_payload()
local_app_id = payload.app_id or "browser"
tool_name = str(payload.raw.get("tool_name") or "")
status_code, result = mcp_result_for_tool(
    Path(payload.data_root),
    tool_name,
    dict(payload.arguments),
    app_id=local_app_id,
    workspace_id=payload.workspace_id,
    effective_mode=payload.effective_mode,
    platform_role=payload.platform_role,
    workspace_role=payload.workspace_role,
    user_id=payload.user_id,
    surface=payload.raw.get("surface"),
    runtime_session_id=payload.runtime_session_id,
    dependencies=payload.raw.get("app_dependencies"),
)
result.update({"app_id": local_app_id, "workspace_id": payload.workspace_id, "tool_name": tool_name, "status_code": status_code})
if status_code < 400:
    result["app_events"] = app_events_for_action(MCP_TOOL_ACTIONS.get(tool_name, ""))
emit_json(result)
