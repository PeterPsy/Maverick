"""MCP entrypoint for the CRM app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from domains.action_catalog import MCP_TOOL_ACTIONS
from errors import CrmError, NotFoundError, error_payload
from service import app_events_for_action, handle_action

payload = read_entrypoint_payload()
tool_name = str(payload.raw.get("tool_name") or "")
try:
    if tool_name:
        action = MCP_TOOL_ACTIONS.get(tool_name)
        if action is None:
            raise NotFoundError(f"CRM MCP tool `{tool_name}` is not declared.")
    else:
        action = "operations.manifest"
    arguments = dict(payload.arguments)
    arguments["_app_dependencies"] = payload.raw.get("app_dependencies", {})
    arguments["_workspace_id"] = payload.workspace_id
    arguments["_app_id"] = payload.app_id
    status_code, result = handle_action(payload.data_root, action, arguments)
except CrmError as error:
    status_code, result = error.status_code, error_payload(error)

response = {"status_code": status_code, "app_id": "crm", "workspace_id": payload.workspace_id, "tool_name": tool_name, **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
