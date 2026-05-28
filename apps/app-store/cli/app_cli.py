"""App Store app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import AppStoreValidationError, app_events_for_action, handle_action, strip_internal_result_fields


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
command = str(payload.get("command_id") or arguments.get("action") or "catalog")
if command == "app-store":
    command = str(arguments.get("action") or "catalog")
try:
    status_code, result = handle_action(Path(payload["data_root"]), {"action": command, **arguments})
except AppStoreValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}
except Exception as error:
    status_code, result = 502, {"error": "catalog_unavailable", "detail": str(error)}

app_events = app_events_for_action(command, result) if status_code < 400 else []
strip_internal_result_fields(result)
response = {"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}
if status_code < 400:
    response["app_events"] = app_events
print(json.dumps(response, ensure_ascii=False))
