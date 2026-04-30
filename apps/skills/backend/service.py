"""Skills app service layer shared by backend, MCP, and CLI."""

from __future__ import annotations

from pathlib import Path

from models import DEFAULT_SKILL_CONTENT
from seeds import seed_default_skills
from store import (
    clear_custom_view_payload,
    delete_skill,
    ensure_data_root,
    get_skill,
    list_skills,
    save_skill,
    set_custom_view_payload,
    set_view_filter_payload,
    skill_markdown,
    view_state,
)

REFERENCE_MANIFEST = {
    "app_id": "skills",
    "schema_version": "1",
    "entity_types": [
        {"entity_type": "skill", "display_name": "Skill", "id_stability": "stable", "searchable": True, "resolvable": True, "summarizable": True, "deep_link_supported": True}
    ],
}

DATA_CHANGED_ACTIONS = {"create_skill", "update_skill", "delete_skill", "sync_bundled_skills"}
VIEW_STATE_ACTIONS = {"set_view_filter", "set_custom_view", "clear_custom_view"}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action in DATA_CHANGED_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "skills"}]
    if action in VIEW_STATE_ACTIONS:
        return [{"type": "maverick.app.data-changed", "resource": "view-state"}]
    return []


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


def sync_bundled_skills(data_root: Path, *, repository_root: Path) -> dict:
    seeded = seed_default_skills(data_root, repository_root=repository_root)
    return {
        "seeded_skill_ids": seeded,
        "skills": list_skills(data_root),
    }


def _skill_reference(item: dict) -> dict:
    return {
        "app_id": "skills",
        "entity_type": "skill",
        "entity_id": item["id"],
        "title": item["name"],
        "subtitle": "Enabled" if item.get("enabled", True) else "Disabled",
        "summary": item.get("description", ""),
        "confidence": 1.0,
        "deep_link": f"/apps/skills/{item['id']}",
    }


def handle_action(data_root: Path, body: dict, *, repository_root: Path | None = None) -> tuple[int, dict]:
    action = str(body.get("action") or "catalog")
    ensure_data_root(data_root)
    if action == "catalog":
        return 200, catalog(data_root)
    if action == "list_skills":
        return 200, {"skills": catalog(data_root)["skills"]}
    if action == "view_filter":
        return 200, {"state": view_state(data_root)}
    if action == "set_view_filter":
        return 200, {"state": set_view_filter_payload(data_root, body)}
    if action == "set_custom_view":
        return 200, {"state": set_custom_view_payload(data_root, body)}
    if action == "clear_custom_view":
        return 200, {"state": clear_custom_view_payload(data_root)}
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
    if action == "sync_bundled_skills":
        if repository_root is None or not repository_root.exists():
            return 400, {"error": "repository_root_required"}
        return 200, sync_bundled_skills(data_root, repository_root=repository_root)
    if action == "preview_markdown":
        return 200, {"markdown": skill_markdown(body)}
    if action == "health.check":
        return 200, {"status": "ok", "skill_count": len(list_skills(data_root))}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        query = str(body.get("query") or "").casefold()
        items = [_skill_reference(item) for item in list_skills(data_root)]
        if query:
            items = [item for item in items if query in item["title"].casefold() or query in item["summary"].casefold() or query in item["entity_id"].casefold()]
        return 200, {"results": items[: max(1, min(int(body.get("limit") or 10), 50))]}
    if action == "references.resolve":
        entity_id = str(body.get("entity_id") or "").strip()
        skill = get_skill(data_root, entity_id)
        return 200, {"exists": False, "app_id": "skills", "entity_type": "skill", "entity_id": entity_id} if skill is None else {"exists": True, **_skill_reference(skill)}
    if action == "references.summarize":
        entity_id = str(body.get("entity_id") or "").strip()
        skill = get_skill(data_root, entity_id)
        return 200, {"summary": "", "safe_fields": {}, "source_updated_at": ""} if skill is None else {
            "summary": skill.get("description", ""),
            "safe_fields": {"name": skill.get("name"), "enabled": skill.get("enabled", True)},
            "source_updated_at": skill.get("updated_at", ""),
        }
    return 400, {"error": "unsupported_action", "action": action}
