"""Agents app service layer shared by backend, MCP, and CLI."""

from __future__ import annotations

from pathlib import Path

from seeds import seed_defaults
from store import (
    AgentsValidationError,
    delete_agent_type,
    delete_role,
    get_agent_type,
    get_role,
    list_agent_types,
    list_roles,
    read_common_prompt,
    save_agent_type,
    save_role,
    write_common_prompt,
)

REFERENCE_MANIFEST = {
    "app_id": "agents",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "agent_type", "display_name": "Agent Type", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
        {"entity_type": "role_prompt", "display_name": "Role Prompt", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True},
    ],
}


def catalog(data_root: Path) -> dict:
    seed_defaults(data_root)
    return {
        "common_prompt": read_common_prompt(data_root),
        "roles": list_roles(data_root),
        "agent_types": list_agent_types(data_root),
    }


def prompt_preview(data_root: Path, body: dict) -> dict:
    agent_type_id = str(body.get("agent_type_id") or "")
    agent_type = get_agent_type(data_root, agent_type_id)
    if agent_type is None:
        raise AgentsValidationError(f"Unknown agent type id: {agent_type_id}")
    role = get_role(data_root, agent_type["role_id"])
    if role is None:
        raise AgentsValidationError(f"Unknown role id: {agent_type['role_id']}")
    sections = [
        {"id": "common_prompt", "title": "Common Prompt", "content": read_common_prompt(data_root).strip()},
        {"id": "role", "title": role["name"], "content": role["instructions"].strip()},
        {
            "id": "agent_type",
            "title": "Agent Type",
            "content": (
                f"Name: {agent_type['name']}\n"
                f"Execution mode: {agent_type['default_execution_mode']}\n"
                f"Execution policy: {agent_type['execution_mode_policy']}\n"
                f"Trace verbosity: {agent_type['trace_verbosity']}\n"
                f"Skills: {', '.join(agent_type['codex_skill_ids']) if agent_type['codex_skill_ids'] else 'none'}"
            ),
        },
    ]
    rendered = "\n\n".join(f"## {section['title']}\n{section['content']}" for section in sections if section["content"])
    return {"sections": sections, "rendered": rendered}


def _reference_items(data_root: Path, entity_type: str) -> list[dict]:
    if entity_type == "agent_type":
        return [
            {
                "app_id": "agents",
                "entity_type": "agent_type",
                "entity_id": item["id"],
                "title": item["name"],
                "subtitle": item.get("role_id", ""),
                "summary": item.get("description", ""),
                "confidence": 1.0,
                "deep_link": f"/apps/agents/agent-types/{item['id']}",
            }
            for item in list_agent_types(data_root)
        ]
    if entity_type == "role_prompt":
        return [
            {
                "app_id": "agents",
                "entity_type": "role_prompt",
                "entity_id": item["id"],
                "title": item["name"],
                "subtitle": "Role prompt",
                "summary": item.get("description", ""),
                "confidence": 1.0,
                "deep_link": f"/apps/agents/roles/{item['id']}",
            }
            for item in list_roles(data_root)
        ]
    raise AgentsValidationError(f"Unsupported reference entity type: {entity_type}")


def reference_search(data_root: Path, body: dict) -> dict:
    entity_type = str(body.get("entity_type") or body.get("type") or "").strip()
    query = str(body.get("query") or "").strip().casefold()
    limit = max(1, min(int(body.get("limit") or 10), 50))
    items = _reference_items(data_root, entity_type)
    if query:
        items = [
            item for item in items
            if query in item["title"].casefold() or query in item["summary"].casefold() or query in item["entity_id"].casefold()
        ]
    return {"results": items[:limit]}


def reference_resolve(data_root: Path, body: dict) -> dict:
    entity_type = str(body.get("entity_type") or body.get("type") or "").strip()
    entity_id = str(body.get("entity_id") or "").strip()
    item = next((candidate for candidate in _reference_items(data_root, entity_type) if candidate["entity_id"] == entity_id), None)
    if item is None:
        return {"exists": False, "app_id": "agents", "entity_type": entity_type, "entity_id": entity_id}
    return {"exists": True, **item}


def reference_summarize(data_root: Path, body: dict) -> dict:
    resolved = reference_resolve(data_root, body)
    if not resolved.get("exists"):
        return {"summary": "", "safe_fields": {}, "source_updated_at": ""}
    return {
        "summary": resolved.get("summary") or resolved.get("title") or "",
        "safe_fields": {"title": resolved.get("title"), "subtitle": resolved.get("subtitle")},
        "source_updated_at": "",
    }


def handle_action(data_root: Path, body: dict) -> tuple[int, dict]:
    action = str(body.get("action") or "catalog")
    seed_defaults(data_root)
    if action == "catalog":
        return 200, catalog(data_root)
    if action == "list_roles":
        return 200, {"roles": list_roles(data_root)}
    if action == "get_role":
        role = get_role(data_root, str(body.get("role_id") or ""))
        return (200, {"role": role}) if role is not None else (404, {"error": "role_not_found"})
    if action in {"create_role", "update_role"}:
        return 200, {"role": save_role(data_root, body)}
    if action == "delete_role":
        deleted = delete_role(data_root, str(body.get("role_id") or ""))
        return (200, {"deleted": True}) if deleted else (404, {"error": "role_not_found"})
    if action == "list_agent_types":
        return 200, {"agent_types": list_agent_types(data_root)}
    if action == "get_agent_type":
        agent_type = get_agent_type(data_root, str(body.get("agent_type_id") or ""))
        return (200, {"agent_type": agent_type}) if agent_type is not None else (404, {"error": "agent_type_not_found"})
    if action in {"create_agent_type", "update_agent_type"}:
        return 200, {"agent_type": save_agent_type(data_root, body)}
    if action == "delete_agent_type":
        deleted = delete_agent_type(data_root, str(body.get("agent_type_id") or ""))
        return (200, {"deleted": True}) if deleted else (404, {"error": "agent_type_not_found"})
    if action == "get_common_prompt":
        return 200, {"common_prompt": read_common_prompt(data_root)}
    if action == "set_common_prompt":
        return 200, {"common_prompt": write_common_prompt(data_root, str(body.get("prompt") or ""))}
    if action == "preview_prompt":
        return 200, prompt_preview(data_root, body)
    if action == "health.check":
        return 200, {"status": "ok", "data_root": str(data_root)}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        return 200, reference_search(data_root, body)
    if action == "references.resolve":
        return 200, reference_resolve(data_root, body)
    if action == "references.summarize":
        return 200, reference_summarize(data_root, body)
    return 400, {"error": "unsupported_action", "action": action}
