"""Storage app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import StorageValidationError
from service import app_events_for_action, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
action_aliases = {
    "write": "file.content.write",
    "write-file": "file.content.write",
    "write-content": "file.content.write",
}
requested_action = str(arguments.get("action") or "catalog")
body = {**arguments, "action": action_aliases.get(requested_action, requested_action)}
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        Path(payload["uploaded_storage_root"]),
        Path(payload["generated_storage_root"]),
        body,
    )
except StorageValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

response = {"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(str(body.get("action") or "catalog"))
print(json.dumps(response, ensure_ascii=False))
