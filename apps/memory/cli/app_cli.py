"""Memory app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import MemoryValidationError
from service import handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
command_id = str(payload.get("command_id") or "")
action = str(arguments.get("action") or "").strip()
if not action and command_id.endswith(".memory"):
    action = "context"
if not action:
    action = str(arguments.get("command") or "context")
try:
    status_code, result = handle_action(Path(payload["data_root"]), {"action": action, **arguments})
except MemoryValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

print(json.dumps({"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}, ensure_ascii=False))

