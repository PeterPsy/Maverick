"""Agents app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import app_events_for_result, handle_action, validation_error_payload
from store import AgentsValidationError


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
command = str(arguments.get("action") or "operations.manifest")
try:
    status_code, result = handle_action(Path(payload["data_root"]), {"action": command, **arguments})
except AgentsValidationError as error:
    status_code, result = 400, validation_error_payload(error, command)

response = {"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}
if status_code < 400:
    response["app_events"] = app_events_for_result(command, result)
print(json.dumps(response, ensure_ascii=False))
