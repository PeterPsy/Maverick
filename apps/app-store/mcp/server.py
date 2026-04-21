"""App Store app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import AppStoreValidationError, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_actions = {
    "app_store_reference_manifest": "references.manifest",
    "app_store_reference_search": "references.search",
    "app_store_reference_resolve": "references.resolve",
    "app_store_reference_summarize": "references.summarize",
}
body = {"action": tool_actions.get(str(payload.get("tool_name") or ""), arguments.get("action") or "catalog"), **arguments}
try:
    status_code, result = handle_action(Path(payload["data_root"]), body)
except AppStoreValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}
except Exception as error:
    status_code, result = 502, {"error": "catalog_unavailable", "detail": str(error)}

print(json.dumps({"status_code": status_code, **result}, ensure_ascii=False))
