"""Document Generator app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import DocumentValidationError
from service import app_events_for_result, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
body = {"action": arguments.get("action") or "generate_document", **arguments}
try:
    uploaded_root = Path(payload["uploaded_storage_root"]) if payload.get("uploaded_storage_root") else None
    status_code, result = handle_action(
        Path(payload["data_root"]),
        Path(payload["generated_storage_root"]),
        body,
        uploaded_root,
        local_app_id=str(payload.get("app_id") or "document-generator"),
    )
except DocumentValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

response = {"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}
if status_code < 400:
    response["app_events"] = app_events_for_result(str(body.get("action") or "generate_document"), result)
print(json.dumps(response, ensure_ascii=False))
