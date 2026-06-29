"""MCP entrypoint for `fusion-connector`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.service import InvocationContext, handle_action


payload = read_entrypoint_payload()
arguments = payload.arguments
tool_actions = {
    "fusion_status": "status",
    "fusion_list_tools": "list_tools",
    "fusion_call_tool": "call_tool",
    "fusion_config_get": "config_get",
    "fusion_config_set": "config_set",
    "fusion_audit_recent": "audit_recent",
    "fusion_operations_manifest": "operations_manifest",
    "fusion_connector_reference_manifest": "reference_manifest",
}
tool_name = str(payload.raw.get("tool_name") or "")
action = tool_actions.get(tool_name) or str(arguments.get("action") or "status")
status_code, result = handle_action(
    Path(payload.data_root),
    action,
    arguments,
    context=InvocationContext(
        surface="mcp",
        workspace_id=payload.workspace_id,
        user_id=payload.user_id,
        runtime_session_id=payload.runtime_session_id,
        effective_mode=payload.effective_mode,
    ),
)
emit_json({"status_code": status_code, "app_id": "fusion-connector", **result})
