"""Skills app service layer shared by backend, MCP, and CLI."""

from __future__ import annotations

from pathlib import Path
import re

from installed_skills import get_installed_agent_skill, list_installed_agent_skills, save_installed_agent_skill
from models import DEFAULT_SKILL_CONTENT
from store import delete_skill, ensure_data_root, get_skill, list_skills, save_skill, skill_markdown, validate_skill_id


def catalog(data_root: Path, *, agent_skill_roots: list[str] | None = None) -> dict:
    ensure_data_root(data_root)
    workspace_skills = list_skills(data_root)
    installed_skills = list_installed_agent_skills(agent_skill_roots)
    workspace_ids = {item["id"] for item in workspace_skills}
    return {"skills": workspace_skills + [item for item in installed_skills if item["id"] not in workspace_ids]}


def new_skill_payload(body: dict) -> dict:
    skill_id = str(body.get("id") or "skill-custom").strip()
    return {
        "id": skill_id,
        "name": str(body.get("name") or "New Skill").strip(),
        "description": str(body.get("description") or "Describe when this skill should be used.").strip(),
        "content": str(body.get("content") or DEFAULT_SKILL_CONTENT).strip(),
        "enabled": bool(body.get("enabled", True)),
    }


def import_skill_id(data_root: Path, installed_skill: dict, requested_id: str | None = None) -> str:
    base = str(requested_id or installed_skill.get("local_id") or installed_skill.get("name") or "imported-skill")
    try:
        candidate = validate_skill_id(base)
    except ValueError:
        candidate = validate_skill_id(re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "imported-skill")
    existing_ids = {item["id"] for item in list_skills(data_root)}
    if candidate not in existing_ids:
        return candidate
    suffix = 2
    while f"{candidate}-{suffix}" in existing_ids:
        suffix += 1
    return f"{candidate}-{suffix}"


def handle_action(data_root: Path, body: dict, *, agent_skill_roots: list[str] | None = None) -> tuple[int, dict]:
    action = str(body.get("action") or "catalog")
    ensure_data_root(data_root)
    if action == "catalog":
        return 200, catalog(data_root, agent_skill_roots=agent_skill_roots)
    if action == "list_skills":
        return 200, {"skills": catalog(data_root, agent_skill_roots=agent_skill_roots)["skills"]}
    if action == "get_skill":
        skill_id = str(body.get("skill_id") or "")
        skill = get_skill(data_root, skill_id)
        if skill is None:
            skill = get_installed_agent_skill(skill_id, agent_skill_roots)
        return (200, {"skill": skill}) if skill is not None else (404, {"error": "skill_not_found"})
    if action in {"create_skill", "update_skill"}:
        payload = new_skill_payload(body) if action == "create_skill" else body
        if action == "update_skill" and get_skill(data_root, str(payload.get("id") or "")) is None:
            installed = save_installed_agent_skill(str(payload.get("id") or ""), payload, agent_skill_roots)
            if installed is not None:
                return 200, {"skill": installed}
        return 200, {"skill": save_skill(data_root, payload)}
    if action == "delete_skill":
        deleted = delete_skill(data_root, str(body.get("skill_id") or ""))
        return (200, {"deleted": True}) if deleted else (404, {"error": "skill_not_found"})
    if action == "import_installed_skill":
        installed = get_installed_agent_skill(str(body.get("skill_id") or ""), agent_skill_roots)
        if installed is None:
            return 404, {"error": "skill_not_found"}
        imported = save_skill(
            data_root,
            {
                "id": import_skill_id(data_root, installed, str(body.get("id") or "").strip() or None),
                "name": installed["name"],
                "description": installed["description"],
                "content": installed["content"],
                "enabled": True,
            },
        )
        return 200, {"skill": imported}
    if action == "preview_markdown":
        return 200, {"markdown": skill_markdown(body)}
    if action == "health.check":
        return 200, {"status": "ok", "skill_count": len(list_skills(data_root))}
    return 400, {"error": "unsupported_action", "action": action}
