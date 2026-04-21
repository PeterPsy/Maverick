"""Document Generator app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import DocumentValidationError
from service import handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
body = {"action": arguments.get("action") or "generate_document", **arguments}
try:
    status_code, result = handle_action(Path(payload["data_root"]), Path(payload["generated_storage_root"]), body)
except DocumentValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

print(json.dumps({"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}, ensure_ascii=False))
