"""Skills app service layer shared by backend, MCP, and CLI."""

from __future__ import annotations

from pathlib import Path

from models import DEFAULT_SKILL_CONTENT
from store import delete_skill, ensure_data_root, get_skill, list_skills, save_skill, skill_markdown


def catalog(data_root: Path) -> dict:
    ensure_data_root(data_root)
    return {"skills": list_skills(data_root)}


def new_skill_payload(body: dict) -> dict:
    skill_id = str(body.get("id") or "skill-custom").strip()
    return {
        "id": skill_id,
        "name": str(body.get("name") or "New Skill").strip(),
        "description": str(body.get("description") or "Describe when this skill should be used.").strip(),
        "content": str(body.get("content") or DEFAULT_SKILL_CONTENT).strip(),
        "enabled": bool(body.get("enabled", True)),
    }


def handle_action(data_root: Path, body: dict) -> tuple[int, dict]:
    action = str(body.get("action") or "catalog")
    ensure_data_root(data_root)
    if action == "catalog":
        return 200, catalog(data_root)
    if action == "list_skills":
        return 200, {"skills": catalog(data_root)["skills"]}
    if action == "get_skill":
        skill_id = str(body.get("skill_id") or "")
        skill = get_skill(data_root, skill_id)
        return (200, {"skill": skill}) if skill is not None else (404, {"error": "skill_not_found"})
    if action in {"create_skill", "update_skill"}:
        payload = new_skill_payload(body) if action == "create_skill" else body
        return 200, {"skill": save_skill(data_root, payload)}
    if action == "delete_skill":
        deleted = delete_skill(data_root, str(body.get("skill_id") or ""))
        return (200, {"deleted": True}) if deleted else (404, {"error": "skill_not_found"})
    if action == "preview_markdown":
        return 200, {"markdown": skill_markdown(body)}
    if action == "health.check":
        return 200, {"status": "ok", "skill_count": len(list_skills(data_root))}
    return 400, {"error": "unsupported_action", "action": action}
