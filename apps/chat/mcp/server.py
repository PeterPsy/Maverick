"""Chat app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from chat_state import (
    clear_custom_view,
    list_projects,
    read_state,
    set_custom_view,
    set_view_filter,
    state_path,
    write_state,
)

REFERENCE_MANIFEST = {
    "app_id": "chat",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "project", "display_name": "Chat Project", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
    ],
}


def reference_items(state: dict, entity_type: str) -> list[dict]:
    if entity_type == "project":
        return [
            {"app_id": "chat", "entity_type": "project", "entity_id": item["project_id"], "title": item["name"], "subtitle": "Chat project", "summary": "", "confidence": 1.0, "deep_link": f"/apps/chat/projects/{item['project_id']}"}
            for item in list_projects(state)
        ]
    return []


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
path = state_path(Path(payload["data_root"]))
state = read_state(path)
tool_name = str(payload.get("tool_name") or "")

if tool_name == "chat_reference_manifest":
    result = REFERENCE_MANIFEST
elif tool_name == "chat_reference_search":
    entity_type = str(arguments.get("entity_type") or arguments.get("type") or "").strip()
    query = str(arguments.get("query") or "").casefold()
    items = reference_items(state, entity_type)
    if query:
        items = [item for item in items if query in item["title"].casefold() or query in item["summary"].casefold()]
    result = {"results": items[: max(1, min(int(arguments.get("limit") or 10), 50))]}
elif tool_name == "chat_reference_resolve":
    entity_type = str(arguments.get("entity_type") or arguments.get("type") or "").strip()
    entity_id = str(arguments.get("entity_id") or "").strip()
    item = next((candidate for candidate in reference_items(state, entity_type) if candidate["entity_id"] == entity_id), None)
    result = {"exists": False, "app_id": "chat", "entity_type": entity_type, "entity_id": entity_id} if item is None else {"exists": True, **item}
elif tool_name == "chat_reference_summarize":
    entity_type = str(arguments.get("entity_type") or arguments.get("type") or "").strip()
    entity_id = str(arguments.get("entity_id") or "").strip()
    item = next((candidate for candidate in reference_items(state, entity_type) if candidate["entity_id"] == entity_id), None)
    result = {"summary": (item or {}).get("summary", ""), "safe_fields": {"title": (item or {}).get("title", ""), "entity_type": entity_type}, "source_updated_at": ""}
elif tool_name == "chat_view_filter":
    result = {"status_code": 200, "state": {"view_filter": state.get("preferences", {}).get("view_filter")}}
elif tool_name == "chat_set_view_filter":
    result = {"status_code": 200, "state": {"view_filter": set_view_filter(state, arguments)}, "app_events": [{"type": "maverick.app.data-changed", "resource": "view-state"}]}
    write_state(path, state)
elif tool_name == "chat_set_custom_view":
    result = {"status_code": 200, "state": {"view_filter": set_custom_view(state, arguments)}, "app_events": [{"type": "maverick.app.data-changed", "resource": "view-state"}]}
    write_state(path, state)
elif tool_name == "chat_clear_custom_view":
    result = {"status_code": 200, "state": {"view_filter": clear_custom_view(state)}, "app_events": [{"type": "maverick.app.data-changed", "resource": "view-state"}]}
    write_state(path, state)
elif tool_name == "message.send":
    result = {
        "accepted": False,
        "reason": "Use the core runtime HTTP surface for live chat messages in the first hosted implementation.",
    }
elif tool_name == "turn.stop":
    result = {"accepted": False, "reason": "Use the core runtime interrupt surface."}
else:
    result = {"accepted": False, "tool_name": tool_name}

print(json.dumps(result))
