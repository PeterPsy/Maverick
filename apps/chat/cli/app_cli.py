"""Chat app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from chat_state import (
    clear_custom_view,
    find_thread,
    list_projects,
    list_threads,
    read_state,
    set_custom_view,
    set_view_filter,
    threads_path,
    write_state,
)

REFERENCE_MANIFEST = {
    "app_id": "chat",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "thread", "display_name": "Chat Thread", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
        {"entity_type": "project", "display_name": "Chat Project", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
    ],
}


def reference_items(state: dict, entity_type: str) -> list[dict]:
    if entity_type == "thread":
        return [
            {
                "app_id": "chat",
                "entity_type": "thread",
                "entity_id": item["thread_id"],
                "title": item["title"],
                "subtitle": item.get("agent_label") or "Chat thread",
                "summary": item.get("system_prompt", "")[:300],
                "confidence": 1.0,
                "deep_link": f"/apps/chat/threads/{item['thread_id']}",
            }
            for item in list_threads(state)
        ]
    if entity_type == "project":
        return [
            {
                "app_id": "chat",
                "entity_type": "project",
                "entity_id": item["project_id"],
                "title": item["name"],
                "subtitle": "Chat project",
                "summary": "",
                "confidence": 1.0,
                "deep_link": f"/apps/chat/projects/{item['project_id']}",
            }
            for item in list_projects(state)
        ]
    return []


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
path = threads_path(Path(payload["data_root"]))
state = read_state(path)
action = str(arguments.get("action") or "").strip()

if action == "references.manifest":
    result = REFERENCE_MANIFEST
elif action == "references.search":
    entity_type = str(arguments.get("entity_type") or arguments.get("type") or "").strip()
    query = str(arguments.get("query") or "").casefold()
    items = reference_items(state, entity_type)
    if query:
        items = [item for item in items if query in item["title"].casefold() or query in item["summary"].casefold()]
    result = {"results": items[: max(1, min(int(arguments.get("limit") or 10), 50))]}
elif action == "references.resolve":
    entity_type = str(arguments.get("entity_type") or arguments.get("type") or "").strip()
    entity_id = str(arguments.get("entity_id") or "").strip()
    item = next((candidate for candidate in reference_items(state, entity_type) if candidate["entity_id"] == entity_id), None)
    result = {"exists": False, "app_id": "chat", "entity_type": entity_type, "entity_id": entity_id} if item is None else {"exists": True, **item}
elif action == "references.summarize":
    entity_type = str(arguments.get("entity_type") or arguments.get("type") or "").strip()
    entity_id = str(arguments.get("entity_id") or "").strip()
    thread = find_thread(state, entity_id) if entity_type == "thread" else None
    item = next((candidate for candidate in reference_items(state, entity_type) if candidate["entity_id"] == entity_id), None)
    result = {
        "summary": (thread or {}).get("system_prompt") or (item or {}).get("summary", ""),
        "safe_fields": {"title": (item or {}).get("title", ""), "entity_type": entity_type},
        "source_updated_at": (thread or {}).get("updated_at", ""),
    }
elif action == "view_filter":
    result = {"state": {"view_filter": state.get("preferences", {}).get("view_filter")}}
elif action == "set_view_filter":
    result = {"state": {"view_filter": set_view_filter(state, arguments)}, "app_events": [{"type": "maverick.app.data-changed", "resource": "view-state"}]}
    write_state(path, state)
elif action == "set_custom_view":
    result = {"state": {"view_filter": set_custom_view(state, arguments)}, "app_events": [{"type": "maverick.app.data-changed", "resource": "view-state"}]}
    write_state(path, state)
elif action == "clear_custom_view":
    result = {"state": {"view_filter": clear_custom_view(state)}, "app_events": [{"type": "maverick.app.data-changed", "resource": "view-state"}]}
    write_state(path, state)
else:
    result = {
        "thread_count": len(state.get("threads", [])),
        "threads": state.get("threads", []),
        "arguments": arguments,
    }

print(json.dumps({"status_code": 200, "workspace_id": payload.get("workspace_id"), "app_id": payload.get("app_id"), **result}, ensure_ascii=False))
