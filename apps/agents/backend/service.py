"""Agents app service layer shared by backend, MCP, and CLI."""

from __future__ import annotations

from pathlib import Path

from seeds import seed_defaults
from store import (
    AgentsValidationError,
    create_instance,
    delete_agent_type,
    delete_instance,
    delete_role,
    get_agent_type,
    get_role,
    list_agent_types,
    list_instances,
    list_roles,
    read_common_prompt,
    save_agent_type,
    save_role,
    update_instance,
    write_common_prompt,
)


def catalog(data_root: Path) -> dict:
    seed_defaults(data_root)
    return {
        "common_prompt": read_common_prompt(data_root),
        "roles": list_roles(data_root),
        "agent_types": list_agent_types(data_root),
        "instances": list_instances(data_root),
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
    if action == "list_instances":
        return 200, {"instances": list_instances(data_root)}
    if action == "create_instance":
        return 201, {"instance": create_instance(data_root, body)}
    if action == "update_instance":
        instance = update_instance(data_root, body)
        return (200, {"instance": instance}) if instance is not None else (404, {"error": "instance_not_found"})
    if action == "delete_instance":
        deleted = delete_instance(data_root, str(body.get("instance_id") or ""))
        return (200, {"deleted": True}) if deleted else (404, {"error": "instance_not_found"})
    if action in {"start_instance", "stop_instance", "send_message_to_instance", "delegate_to_agent"}:
        return 409, {
            "accepted": False,
            "error": "runtime_binding_not_available",
            "detail": "Agent runtime execution requires the generic v3 runtime launch contract.",
        }
    if action == "health.check":
        return 200, {"status": "ok", "data_root": str(data_root)}
    return 400, {"error": "unsupported_action", "action": action}
