"""Agent-facing Checklist operation metadata and guided errors."""

from __future__ import annotations

from typing import Any


ACTION_ALIASES = {
    "create_plan": "create",
    "get": "read",
    "recall": "read",
    "add_item": "add_task",
    "toggle_item": "toggle_task",
}
ALLOWED_ACTIONS = [
    "operations.manifest",
    "describe",
    "list",
    "read",
    "create",
    "create_plan",
    "update",
    "delete",
    "add_task",
    "add_item",
    "toggle_task",
    "toggle_item",
    "set_task_status",
    "set_subtask_status",
    "next_actions",
    "references.manifest",
    "references.search",
    "references.resolve",
    "references.summarize",
    "view_filter",
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
]
EXPECTED_FIELDS_BY_ACTION = {
    "read": ["id"],
    "update": ["id"],
    "delete": ["id"],
    "add_task": ["id", "title"],
    "toggle_task": ["id", "section_id", "task_id"],
    "set_task_status": ["id", "section_id", "task_id", "status"],
    "set_subtask_status": ["id", "section_id", "task_id", "subtask_id", "status"],
    "references.resolve": ["entity_id"],
    "references.summarize": ["entity_id"],
}


def normalize_action(value: Any) -> str:
    """Return the canonical action name for a public alias."""
    action = str(value or "operations.manifest").strip().lower()
    return ACTION_ALIASES.get(action, action)


def operations_manifest() -> dict[str, Any]:
    """Return the compact agent-facing operation manifest."""
    return {
        "action": "operations.manifest",
        "app_id": "checklist",
        "schema_version": "1",
        "default_action": "operations.manifest",
        "commands": [
            {
                "surface": "cli",
                "name": "checklist",
                "description": "Manage workspace checklists. Calling without arguments returns this manifest.",
            },
            {
                "surface": "cli",
                "name": "checklist-reference",
                "description": "Search, resolve, and summarize checklist app references.",
            },
            {
                "surface": "cli",
                "name": "checklist-view",
                "description": "Read or update Checklist board view state.",
            },
        ],
        "tools": [
            {"surface": "mcp", "name": "checklist_tasklist", "description": "Generic Checklist operation runner."},
            {"surface": "mcp", "name": "checklist_list", "operation": "list"},
            {"surface": "mcp", "name": "checklist_create", "operation": "create"},
            {"surface": "mcp", "name": "checklist_read", "operation": "read"},
            {"surface": "mcp", "name": "checklist_update", "operation": "update"},
            {"surface": "mcp", "name": "checklist_set_task_status", "operation": "set_task_status"},
            {"surface": "mcp", "name": "checklist_next_actions", "operation": "next_actions"},
            {"surface": "mcp", "name": "checklist_reference_search", "operation": "references.search"},
            {"surface": "mcp", "name": "checklist_reference_resolve", "operation": "references.resolve"},
        ],
        "recommended": [
            {"task": "discover_operations", "operation": "operations.manifest", "calls_required": 1},
            {
                "task": "list_checklists_compact",
                "operation": "list",
                "calls_required": 1,
                "example": {"action": "list", "limit": 20},
            },
            {
                "task": "read_one_checklist_full",
                "operation": "read",
                "calls_required": 1,
                "example": {"action": "read", "id": "check_<id>"},
            },
            {
                "task": "create_agent_plan",
                "operation": "create",
                "calls_required": 1,
                "example": {"action": "create", "title": "Launch plan", "mode": "agent_plan"},
            },
            {
                "task": "update_task_status",
                "operation": "set_task_status",
                "calls_required": 1,
                "example": {
                    "action": "set_task_status",
                    "id": "check_<id>",
                    "section_id": "main",
                    "task_id": "task-1",
                    "status": "completed",
                },
            },
        ],
        "operations": [
            {
                "action": "list",
                "description": "List checklists with compact records by default.",
                "optional": ["profile", "offset", "limit", "ignore_view_state", "include_content"],
                "payload_profile": "compact_by_default",
            },
            {
                "action": "read",
                "aliases": ["get", "recall"],
                "description": "Read one full checklist by id.",
                "required": ["id"],
                "payload_profile": "full_by_id",
            },
            {
                "action": "create",
                "aliases": ["create_plan"],
                "description": "Create one workspace checklist or agent plan.",
                "required_any": ["title", "payload"],
                "optional": ["summary", "mode", "status", "priority", "profile", "sections"],
                "payload_profile": "single_record_full",
            },
            {
                "action": "update",
                "description": "Update one checklist by id.",
                "required": ["id"],
                "payload_profile": "single_record_full",
            },
            {
                "action": "delete",
                "description": "Delete one checklist by id.",
                "required": ["id"],
                "payload_profile": "single_delete_result",
            },
            {
                "action": "set_task_status",
                "description": "Set one task status.",
                "required": ["id", "section_id", "task_id", "status"],
                "payload_profile": "single_task",
            },
            {
                "action": "set_subtask_status",
                "description": "Set one subtask status.",
                "required": ["id", "section_id", "task_id", "subtask_id", "status"],
                "payload_profile": "single_subtask",
            },
            {
                "action": "next_actions",
                "description": "Return up to 50 open tasks sorted for execution.",
                "payload_profile": "compact_task_queue",
            },
            {
                "action": "references.search",
                "description": "Search checklist references.",
                "optional": ["query", "limit"],
                "payload_profile": "compact_references",
            },
            {
                "action": "references.resolve",
                "description": "Resolve one checklist reference.",
                "required": ["entity_id"],
                "payload_profile": "single_reference",
            },
            {
                "action": "view_filter",
                "description": "Read Checklist board view state.",
                "payload_profile": "view_state",
            },
        ],
        "payload_profiles": {
            "operations.manifest": "compact_default",
            "list": "compact_by_default",
            "list.include_content": "explicit_full_list",
            "read": "full_by_explicit_id",
            "create": "single_record_full",
            "update": "single_record_full",
            "next_actions": "compact_open_tasks",
            "references.search": "compact_results",
            "references.resolve": "single_reference",
            "references.summarize": "single_reference_summary",
        },
        "aliases": ACTION_ALIASES,
        "id_patterns": {
            "checklist_id": "check_<hex>",
            "section_id": "section-default or app-provided section id",
            "task_id": "task-<id> or app-provided task id",
        },
        "allowed_statuses": {
            "task": ["pending", "in-progress", "need-help", "blocked", "completed", "failed"],
            "checklist": ["active", "in-progress", "blocked", "completed", "failed"],
        },
        "policy": {
            "sandbox_agent_allowed": True,
            "requires_workspace_context": True,
            "requires_full_access": False,
        },
    }


def validation_error(action: str, detail: str) -> dict[str, Any]:
    """Return a structured validation error with corrective metadata."""
    expected_fields = EXPECTED_FIELDS_BY_ACTION.get(action, [])
    response: dict[str, Any] = {
        "error": "validation_error",
        "operation": action,
        "detail": detail,
        "expected_fields": expected_fields,
        "example": _example_for_action(action),
    }
    if "id" in expected_fields:
        response["accepted_aliases"] = {"id": ["checklist_id"]}
    if action in {"set_task_status", "set_subtask_status"}:
        response["allowed_values"] = {
            "status": ["pending", "in-progress", "need-help", "blocked", "completed", "failed"]
        }
    if detail.startswith("limit "):
        response["allowed_values"] = {"limit": _limit_bounds_for_action(action)}
    if detail.startswith("offset "):
        response["allowed_values"] = {"offset": {"minimum": 0}}
    return response


def not_found_error(action: str, detail: str) -> dict[str, Any]:
    """Return a structured not-found error without missing-field hints."""
    response: dict[str, Any] = {
        "error": "not_found",
        "operation": action,
        "detail": detail,
        "expected_fields": [],
        "example": _example_for_action(action),
    }
    entity_id = _entity_id_from_detail(detail)
    if entity_id:
        response["entity_type"] = "checklist"
        response["entity_id"] = entity_id
    return response


def unsupported_action(action: str) -> dict[str, Any]:
    """Return a structured unsupported-action error with allowed values."""
    return {
        "error": "unsupported_action",
        "operation": action,
        "detail": f"Unsupported action `{action}`.",
        "allowed_values": {"action": ALLOWED_ACTIONS},
        "accepted_aliases": ACTION_ALIASES,
        "example": {"action": "operations.manifest"},
    }


def _example_for_action(action: str) -> dict[str, Any]:
    examples = {
        "read": {"action": "read", "id": "check_<id>"},
        "update": {"action": "update", "id": "check_<id>", "payload": {"title": "Updated plan"}},
        "delete": {"action": "delete", "id": "check_<id>"},
        "add_task": {"action": "add_task", "id": "check_<id>", "section_id": "main", "title": "Next task"},
        "set_task_status": {
            "action": "set_task_status",
            "id": "check_<id>",
            "section_id": "main",
            "task_id": "task-1",
            "status": "completed",
        },
        "set_subtask_status": {
            "action": "set_subtask_status",
            "id": "check_<id>",
            "section_id": "main",
            "task_id": "task-1",
            "subtask_id": "sub-1",
            "status": "blocked",
        },
        "references.resolve": {"action": "references.resolve", "entity_id": "check_<id>"},
        "references.summarize": {"action": "references.summarize", "entity_id": "check_<id>"},
    }
    return examples.get(action, {"action": action})


def _limit_bounds_for_action(action: str) -> dict[str, int]:
    maximum = 50 if action == "references.search" else 500
    return {"minimum": 1, "maximum": maximum}


def _entity_id_from_detail(detail: str) -> str:
    marker = "Checklist `"
    if marker not in detail:
        return ""
    return detail.split(marker, 1)[1].split("`", 1)[0]
