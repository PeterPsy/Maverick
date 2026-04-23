"""Gallery app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import GalleryValidationError
from service import app_events_for_action, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_actions = {
    "gallery_reference_manifest": "references.manifest",
    "gallery_reference_search": "references.search",
    "gallery_reference_resolve": "references.resolve",
    "gallery_reference_summarize": "references.summarize",
}
body = {"action": tool_actions.get(str(payload.get("tool_name") or ""), arguments.get("action") or "catalog"), **arguments}
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        Path(payload["uploaded_storage_root"]),
        Path(payload["generated_storage_root"]),
        body,
    )
except GalleryValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

response = {"status_code": status_code, **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(str(body.get("action") or "catalog"))
print(json.dumps(response, ensure_ascii=False))
