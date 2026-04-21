"""Agents app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import handle_action
from store import AgentsValidationError


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_actions = {
    "agents_reference_manifest": "references.manifest",
    "agents_reference_search": "references.search",
    "agents_reference_resolve": "references.resolve",
    "agents_reference_summarize": "references.summarize",
}
body = {"action": tool_actions.get(str(payload.get("tool_name") or ""), arguments.get("action") or "catalog"), **arguments}
try:
    status_code, result = handle_action(Path(payload["data_root"]), body)
except AgentsValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

print(json.dumps({"status_code": status_code, **result}, ensure_ascii=False))
