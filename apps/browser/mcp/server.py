"""MCP entrypoint for the Browser app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import mcp_result_for_tool


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
)
result.update({"app_id": local_app_id, "workspace_id": payload.workspace_id, "tool_name": tool_name, "status_code": status_code})
emit_json(result)
