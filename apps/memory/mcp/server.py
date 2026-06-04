"""Memory app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import MemoryValidationError
from entrypoint_errors import storage_error_response
from service import MCP_TOOL_ACTIONS, action_from_tool, app_events_for_action, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_name = str(payload.get("tool_name") or "")
action = action_from_tool(tool_name, "context")
app_id = str(payload.get("app_id") or "memory")
try:
    if tool_name in MCP_TOOL_ACTIONS and "action" in arguments:
        raise MemoryValidationError("MCP tool arguments must not include action.")
    status_code, result = handle_action(
        Path(payload["data_root"]),
        {**arguments, "action": action},
        app_id=app_id,
    )
except MemoryValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}
except sqlite3.Error as error:
    status_code, result = storage_error_response(error, app_id=app_id, action=action)

event_action = result.pop("_event_action", action) if isinstance(result, dict) else action
response = {"status_code": status_code, **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(event_action)
print(json.dumps(response, ensure_ascii=False))
