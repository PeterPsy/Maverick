"""Memory app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import MemoryValidationError
from entrypoint_errors import storage_error_response
from service import app_events_for_action, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
command_id = str(payload.get("command_id") or "")
action = str(arguments.get("action") or "").strip()
app_id = str(payload.get("app_id") or "memory")
if not action and command_id.endswith(".memory"):
    action = "context"
if not action:
    action = str(arguments.get("command") or "context")
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        {"action": action, **arguments},
        app_id=app_id,
    )
except MemoryValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}
except sqlite3.Error as error:
    status_code, result = storage_error_response(error, app_id=app_id, action=action)

response = {"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
print(json.dumps(response, ensure_ascii=False))
