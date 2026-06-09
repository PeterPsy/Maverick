"""MCP entrypoint for Fitness Coach."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, error_payload, FitnessCoachError, handle_action, MCP_TOOL_ACTIONS, NotFoundError


payload = read_entrypoint_payload()
tool_name = str(payload.raw.get("tool_name") or "")

try:
    if tool_name:
        action = MCP_TOOL_ACTIONS.get(tool_name)
        if action is None:
            raise NotFoundError(f"Fitness Coach MCP tool `{tool_name}` is not declared.")
    else:
        action = "operations.manifest"
    arguments = dict(payload.arguments)
    arguments["_app_dependencies"] = payload.raw.get("app_dependencies", {})
    arguments["_workspace_id"] = payload.workspace_id
    arguments["_app_id"] = payload.app_id
    status_code, result = handle_action(payload.data_root, action, arguments)
except FitnessCoachError as error:
    action = ""
    status_code, result = error.status_code, error_payload(error)

response = {"status_code": status_code, "app_id": "fitness-coach", "workspace_id": payload.workspace_id, "tool_name": tool_name, **result}
if status_code < 400 and action:
    events = app_events_for_action(action)
    if events:
        response["app_events"] = events
emit_json(response)
