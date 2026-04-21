"""CRM app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import CrmValidationError
from service import action_from_tool, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
action = action_from_tool(str(payload.get("tool_name") or ""), str(arguments.get("action") or "search"))
try:
    status_code, result = handle_action(Path(payload["data_root"]), {"action": action, **arguments})
except CrmValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

print(json.dumps({"status_code": status_code, **result}, ensure_ascii=False))
