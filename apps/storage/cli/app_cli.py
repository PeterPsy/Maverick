"""Storage app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import StorageValidationError, validation_error_payload
from operations_manifest import STORAGE_ACTION_ALIASES
from service import app_events_for_action, handle_action, secret_lookup_for_drive_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
requested_action = str(arguments.get("action") or "operations.manifest")
body = {
    **arguments,
    "_app_secrets": payload.get("app_secrets", {}),
    "action": STORAGE_ACTION_ALIASES.get(requested_action, requested_action),
}
if payload.get("surface") == "secret_selector":
    print(
        json.dumps(
            secret_lookup_for_drive_action(
                Path(payload["data_root"]),
                Path(payload["uploaded_storage_root"]),
                Path(payload["generated_storage_root"]),
                body,
            ),
            ensure_ascii=False,
        )
    )
    raise SystemExit(0)
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        Path(payload["uploaded_storage_root"]),
        Path(payload["generated_storage_root"]),
        body,
    )
except StorageValidationError as error:
    status_code, result = 400, validation_error_payload(error)

response = {"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(str(body.get("action") or "catalog"))
print(json.dumps(response, ensure_ascii=False))
