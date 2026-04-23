"""Service logic for the ported Checklist workspace app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from store import (
    CHECKLIST_KIND,
    REFERENCE_ENTITY_TYPE,
    WIDGET_CONTENT_KIND,
    add_task,
    clear_custom_view,
    create_checklist,
    delete_checklist,
    list_checklists,
    read_view_filter,
    read_checklist,
    reference_manifest,
    reference_resolve,
    reference_search,
    reference_summarize,
    set_custom_view,
    set_view_filter,
    toggle_task,
    tool_payload,
    update_checklist,
)


MUTATING_ACTIONS = {
    "create",
    "update",
    "delete",
    "add_task",
    "add_item",
    "toggle_task",
    "toggle_item",
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
}


def handle_action(data_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Dispatch backend/CLI/MCP actions."""
    action = str(body.get("action") or "list").strip().lower()
    try:
        if action in {"status", "describe", "schema", "help"}:
            return 200, describe(data_root)
        if action == "list":
            return 200, {
                "action": "list",
                "summary": "tasklist list",
                "items": list_checklists(
                    data_root,
                    profile=_optional(body.get("profile")),
                    limit=_positive_int(body.get("limit")),
                ),
            }
        if action == "references.manifest":
            return 200, reference_manifest()
        if action == "references.search":
            return 200, reference_search(data_root, query=str(body.get("query") or ""), limit=_positive_int(body.get("limit")))
        if action == "references.resolve":
            return 200, reference_resolve(
                data_root,
                entity_type=str(body.get("entity_type") or REFERENCE_ENTITY_TYPE),
                entity_id=str(body.get("entity_id") or body.get("id") or ""),
            )
        if action == "references.summarize":
            return 200, reference_summarize(
                data_root,
                entity_type=str(body.get("entity_type") or REFERENCE_ENTITY_TYPE),
                entity_id=str(body.get("entity_id") or body.get("id") or ""),
            )
        if action == "view_filter":
            return 200, {"action": "view_filter", "view_state": read_view_filter(data_root)}
        if action == "set_view_filter":
            return 200, {
                "action": "set_view_filter",
                "view_state": set_view_filter(data_root, query=str(body.get("query") or "")),
            }
        if action == "set_custom_view":
            return 200, {
                "action": "set_custom_view",
                "view_state": set_custom_view(
                    data_root,
                    title=str(body.get("title") or "Checklist view"),
                    refs=body.get("refs"),
                ),
            }
        if action == "clear_custom_view":
            return 200, {"action": "clear_custom_view", "view_state": clear_custom_view(data_root)}
        if action in {"read", "get", "recall"}:
            checklist = read_checklist(data_root, _required_id(body))
            return 200, tool_payload("read", checklist)
        if action == "create":
            checklist = create_checklist(data_root, _payload(body))
            return 201, tool_payload("create", checklist)
        if action == "update":
            checklist = update_checklist(data_root, _required_id(body), _payload(body))
            return 200, tool_payload("update", checklist)
        if action == "delete":
            return 200, {"action": "delete", **delete_checklist(data_root, _required_id(body))}
        if action in {"add_task", "add_item"}:
            task = add_task(
                data_root,
                checklist_id=_required_id(body),
                section_id=_optional(body.get("section_id")),
                title=str(body.get("title") or body.get("text") or ""),
            )
            return 201, {"action": "add_task", "task": task}
        if action in {"toggle_task", "toggle_item"}:
            task = toggle_task(
                data_root,
                checklist_id=_required_id(body),
                section_id=str(body.get("section_id") or "section-default"),
                task_id=str(body.get("task_id") or body.get("item_id") or ""),
            )
            return 200, {"action": "toggle_task", "task": task}
    except ValueError as error:
        return 400, {"error": "validation_error", "detail": str(error)}
    return 400, {"error": "unsupported_action", "detail": f"Unsupported action `{action}`."}


def describe(data_root: Path) -> dict[str, Any]:
    """Return tasklist tool metadata."""
    items = list_checklists(data_root, limit=1)
    return {
        "app_id": "checklist",
        "kind": CHECKLIST_KIND,
        "status": "ready",
        "checklist_count": len(list_checklists(data_root)),
        "latest": items[0] if items else None,
        "actions": ["create", "list", "read", "recall", "update", "delete", "add_task", "toggle_task"],
        "reference_manifest": reference_manifest(),
        "view_actions": ["view_filter", "set_view_filter", "set_custom_view", "clear_custom_view"],
        "content_kind": CHECKLIST_KIND,
        "widget_content_kind": WIDGET_CONTENT_KIND,
        "widget": {
            "owner_app_id": "checklist",
            "widget_id": "design-checklist",
            "host": "chat",
            "content_kinds": [WIDGET_CONTENT_KIND],
        },
    }


def app_events_for_action(action: str) -> list[dict[str, str]]:
    """Return app data-change events for mutating actions."""
    if action.strip().lower() not in MUTATING_ACTIONS:
        return []
    return [{"type": "maverick.app.data-changed", "owner_app_id": "checklist", "resource": "state"}]


def mcp_result_for_tool(data_root: Path, tool_name: str, arguments: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Map v3 MCP tools to the v2 maverick_tasklist behavior."""
    if tool_name == "checklist_reference_manifest":
        return 200, reference_manifest()
    if tool_name == "maverick_tasklist":
        body = _payload(arguments)
        body["action"] = str(arguments.get("action") or body.get("action") or "list")
        if arguments.get("id") and "id" not in body:
            body["id"] = arguments["id"]
        return handle_action(data_root, body)
    action_by_tool = {
        "checklist_list": "list",
        "checklist_create": "create",
        "checklist_read": "read",
        "checklist_update": "update",
        "checklist_delete": "delete",
        "checklist_add_task": "add_task",
        "checklist_toggle_task": "toggle_task",
        "checklist_reference_search": "references.search",
        "checklist_reference_resolve": "references.resolve",
        "checklist_reference_summarize": "references.summarize",
        "checklist_view_filter": "view_filter",
        "checklist_set_view_filter": "set_view_filter",
        "checklist_set_custom_view": "set_custom_view",
        "checklist_clear_custom_view": "clear_custom_view",
    }
    arguments.setdefault("action", action_by_tool.get(tool_name, "list"))
    return handle_action(data_root, arguments)


def _payload(body: dict[str, Any]) -> dict[str, Any]:
    payload = body.get("payload")
    if isinstance(payload, dict):
        return {**payload, **{key: value for key, value in body.items() if key in {"id", "workspace_id", "profile"}}}
    return dict(body)


def _required_id(body: dict[str, Any]) -> str:
    value = str(body.get("id") or body.get("checklist_id") or "").strip()
    if not value:
        raise ValueError("Checklist id is required.")
    return value


def _positive_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return None


def _optional(value: Any) -> str | None:
    text = str(value if value is not None else "").strip()
    return text or None
