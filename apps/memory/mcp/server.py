"""Memory app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import MemoryValidationError
from service import action_from_tool, app_events_for_action, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
action = action_from_tool(str(payload.get("tool_name") or ""), str(arguments.get("action") or "context"))
try:
    status_code, result = handle_action(Path(payload["data_root"]), {"action": action, **arguments})
except MemoryValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

response = {"status_code": status_code, **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
print(json.dumps(response, ensure_ascii=False))
