"""Dynamic Views app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import DynamicViewsValidationError
from service import handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
body = {"action": arguments.get("action") or "list", **arguments}
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        workspace_id=str(payload.get("workspace_id") or "default"),
        source_instance_id=str(payload.get("source_instance_id") or "").strip() or None,
        body=body,
    )
except DynamicViewsValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

print(json.dumps({"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}, ensure_ascii=False))
