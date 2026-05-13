"""Storage app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import StorageValidationError
from service import app_events_for_action, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_actions = {
    "storage_reference_manifest": "references.manifest",
    "storage_reference_search": "references.search",
    "storage_reference_resolve": "references.resolve",
    "storage_reference_summarize": "references.summarize",
    "storage_view_filter": "view_filter",
    "storage_set_view_filter": "set_view_filter",
    "storage_set_custom_view": "set_custom_view",
    "storage_clear_custom_view": "clear_custom_view",
    "storage_write_file": "file.content.write",
}
body = {"action": tool_actions.get(str(payload.get("tool_name") or ""), arguments.get("action") or "catalog"), **arguments}
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        Path(payload["uploaded_storage_root"]),
        Path(payload["generated_storage_root"]),
        body,
    )
except StorageValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

response = {"status_code": status_code, **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(str(body.get("action") or "catalog"))
print(json.dumps(response, ensure_ascii=False))
