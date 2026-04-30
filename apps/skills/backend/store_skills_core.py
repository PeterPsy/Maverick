"""JSON and markdown-backed storage for workspace-owned skills."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from core.app_sdk.storage import read_json_state, update_json_state, write_json_state
from models import DEFAULT_SKILL_CONTENT, SCHEMA_VERSION, SKILL_ID_PATTERN


class SkillsValidationError(ValueError):
    """Raised when app-owned skill data is invalid."""



def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()



def state_path(data_root: Path) -> Path:
    return data_root / "state.json"



def skills_root(data_root: Path) -> Path:
    return data_root / "skills"



def ensure_data_root(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    skills_root(data_root).mkdir(parents=True, exist_ok=True)
    if not state_path(data_root).exists():
        write_json(state_path(data_root), {"schema_version": SCHEMA_VERSION, "skills": []})



def write_json(path: Path, payload: dict) -> None:
    write_json_state(path.parent, path.name, payload)



def read_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        payload = read_json_state(path.parent, path.name, default)
    except json.JSONDecodeError:
        return default
    return payload if isinstance(payload, dict) else default



def validate_skill_id(skill_id: str) -> str:
    normalized = str(skill_id or "").strip()
    if not SKILL_ID_PATTERN.match(normalized):
        raise SkillsValidationError(f"Invalid skill_id: {normalized}")
    return normalized



def skill_dir(data_root: Path, skill_id: str) -> Path:
    normalized = validate_skill_id(skill_id)
    root = skills_root(data_root).resolve()
    path = (root / normalized).resolve()
    if root != path and root not in path.parents:
        raise SkillsValidationError("Skill path escaped skills data root.")
    return path



def skill_file(data_root: Path, skill_id: str) -> Path:
    return skill_dir(data_root, skill_id) / "SKILL.md"



def normalize_title(value: str, fallback: str, field_name: str) -> str:
    normalized = " ".join(str(value or fallback).split()).strip()
    if not normalized:
        raise SkillsValidationError(f"{field_name} is required.")
    return normalized



def normalize_description(value: str) -> str:
    return " ".join(str(value or "").split()).strip()



def parse_skill_markdown(raw: str, *, skill_id: str, metadata: dict | None = None) -> dict:
    if not raw.startswith("---\n"):
        raise SkillsValidationError(f"Skill `{skill_id}` is missing frontmatter.")
    try:
        _prefix, remainder = raw.split("---\n", 1)
        header, body = remainder.split("\n---\n", 1)
    except ValueError as error:
        raise SkillsValidationError(f"Skill `{skill_id}` has invalid frontmatter.") from error
    fields: dict[str, str] = {}
    for line in header.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    name = normalize_title(fields.get("name") or "", skill_id, "name")
    description = normalize_description(fields.get("description") or "")
    content = body.strip()
    if not content:
        raise SkillsValidationError(f"Skill `{skill_id}` has empty content.")
    item = metadata.copy() if metadata else {}
    item.update(
        {
            "id": skill_id,
            "name": name,
            "description": description,
            "content": content,
            "markdown": skill_markdown(
                {
                    "id": skill_id,
                    "name": name,
                    "description": description,
                    "content": content,
                }
            ),
        }
    )
    return item



def skill_markdown(skill: dict) -> str:
    skill_id = validate_skill_id(str(skill.get("id") or ""))
    name = normalize_title(str(skill.get("name") or ""), skill_id, "name")
    description = normalize_description(str(skill.get("description") or ""))
    content = str(skill.get("content") or DEFAULT_SKILL_CONTENT).strip()
    if not content:
        raise SkillsValidationError("Skill content is required.")
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{content}\n"



def read_state(data_root: Path) -> dict:
    ensure_data_root(data_root)
    payload = read_json(state_path(data_root), {"schema_version": SCHEMA_VERSION, "skills": []})
    return _normalized_state_payload(payload)



def _normalized_state_payload(payload: dict) -> dict:
    if payload.get("schema_version") != SCHEMA_VERSION:
        payload["schema_version"] = SCHEMA_VERSION
    skills = payload.get("skills") if isinstance(payload.get("skills"), list) else []
    payload["skills"] = [item for item in skills if isinstance(item, dict)]
    return payload



def write_state(data_root: Path, skills: list[dict]) -> None:
    update_json_state(
        data_root,
        "state.json",
        lambda current: {
            "schema_version": SCHEMA_VERSION,
            "skills": skills,
            "view_filter": normalize_view_filter(current.get("view_filter")),
        },
        default={"schema_version": SCHEMA_VERSION, "skills": []},
    )



def default_view_filter() -> dict:
    return {
        "mode": "search",
        "query": "",
        "enabled": "all",
        "title": "",
        "refs": [],
        "updated_at": now_timestamp(),
    }



def normalize_view_filter(raw_filter: object) -> dict:
    if not isinstance(raw_filter, dict):
        raw_filter = {}
    enabled = str(raw_filter.get("enabled") or "all").strip().lower() or "all"
    if enabled not in {"all", "enabled", "disabled"}:
        enabled = "all"
    refs = []
    for item in raw_filter.get("refs") if isinstance(raw_filter.get("refs"), list) else []:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id") or "").strip()
        if str(item.get("entity_type") or "") == "skill" and entity_id:
            refs.append({"entity_type": "skill", "entity_id": entity_id})
    return {
        "mode": "custom" if str(raw_filter.get("mode") or "") == "custom" else "search",
        "query": str(raw_filter.get("query") or "").strip(),
        "enabled": enabled,
        "title": str(raw_filter.get("title") or "").strip(),
        "refs": refs,
        "updated_at": str(raw_filter.get("updated_at") or now_timestamp()),
    }



def view_state(data_root: Path) -> dict:
    state = update_json_state(
        data_root,
        "state.json",
        lambda current: _normalized_state_payload(current),
        default={"schema_version": SCHEMA_VERSION, "skills": []},
    )
    return {"view_filter": state["view_filter"]}



def set_view_filter_payload(data_root: Path, payload: dict) -> dict:
    def _update(state: dict) -> dict:
        current = normalize_view_filter(state.get("view_filter"))
        preserve_custom = bool(payload.get("preserve_custom")) and current.get("mode") == "custom"
        state["schema_version"] = SCHEMA_VERSION
        state["skills"] = state.get("skills") if isinstance(state.get("skills"), list) else []
        state["view_filter"] = normalize_view_filter(
            {
                "mode": "custom" if preserve_custom else "search",
                "query": payload.get("query") if "query" in payload else current.get("query"),
                "enabled": payload.get("enabled") if "enabled" in payload else current.get("enabled"),
                "title": current.get("title") if preserve_custom else "",
                "refs": current.get("refs") if preserve_custom else [],
                "updated_at": now_timestamp(),
            }
        )
        return state

    state = update_json_state(data_root, "state.json", _update, default={"schema_version": SCHEMA_VERSION, "skills": []})
    return {"view_filter": state["view_filter"]}
