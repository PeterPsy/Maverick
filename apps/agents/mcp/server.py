"""Agents app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from service import app_events_for_result, handle_action, validation_error_payload
from store import AgentsValidationError


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_actions = {
    "agents_catalog_compact": "catalog.compact",
    "agents_get_agent_definition": "get_agent_definition",
    "agents_upsert_agent_definition": "upsert_agent_definition",
    "agents_reference_manifest": "references.manifest",
    "agents_reference_search": "references.search",
    "agents_reference_resolve": "references.resolve",
    "agents_reference_summarize": "references.summarize",
    "agents_view_filter": "view_filter",
    "agents_set_view_filter": "set_view_filter",
    "agents_set_custom_view": "set_custom_view",
    "agents_clear_custom_view": "clear_custom_view",
}
mapped_action = tool_actions.get(str(payload.get("tool_name") or ""))
body = {**arguments, "action": mapped_action or arguments.get("action") or "operations.manifest"}
try:
    status_code, result = handle_action(Path(payload["data_root"]), body)
except AgentsValidationError as error:
    status_code, result = 400, validation_error_payload(error, str(body.get("action") or "operations.manifest"))

response = {"status_code": status_code, **result}
if status_code < 400:
    response["app_events"] = app_events_for_result(str(body.get("action") or "operations.manifest"), result)
print(json.dumps(response, ensure_ascii=False))
