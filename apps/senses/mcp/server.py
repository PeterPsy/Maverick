"""MCP entrypoint for Senses."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action


TOOL_ACTIONS = {
    "senses_operations_manifest": "manifest",
    "senses_reference_manifest": "reference_manifest",
    "senses_view_filter": "view_filter",
    "senses_set_view_filter": "set_view_filter",
    "senses_set_custom_view": "set_custom_view",
    "senses_clear_custom_view": "clear_custom_view",
}


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
tool_name = str(payload.raw.get("tool_name") or "").strip()
action = TOOL_ACTIONS.get(tool_name)
if action is None:
    emit_json(
        {
            "ok": False,
            "error": "unsupported_tool",
            "detail": f"Unsupported Senses MCP tool `{tool_name or '<missing>'}`.",
            "allowed_tools": sorted(TOOL_ACTIONS),
        }
    )
    raise SystemExit(0)
arguments["_workspace_id"] = payload.workspace_id
arguments["_app_id"] = payload.app_id
arguments["_app_dependencies"] = payload.raw.get("app_dependencies", {})
arguments["_app_actor"] = {
    "user_id": payload.user_id,
    "workspace_role": payload.workspace_role,
    "platform_role": payload.platform_role,
    "effective_mode": payload.effective_mode,
}
arguments["action"] = action
status_code, result = handle_action(Path(payload.data_root), arguments)
if status_code < 400:
    result["app_events"] = app_events_for_action(action)
emit_json(result)
