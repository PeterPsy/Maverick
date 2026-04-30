"""JSON and markdown-backed storage for workspace-owned skills."""

from __future__ import annotations

from pathlib import Path

from core.app_sdk.storage import update_json_state
from models import SCHEMA_VERSION


def set_custom_view_payload(data_root: Path, payload: dict) -> dict:
    def _update(state: dict) -> dict:
        state["schema_version"] = SCHEMA_VERSION
        state["skills"] = state.get("skills") if isinstance(state.get("skills"), list) else []
        state["view_filter"] = normalize_view_filter(
            {
                "mode": "custom",
                "query": payload.get("query"),
                "enabled": payload.get("enabled"),
                "title": payload.get("title"),
                "refs": payload.get("refs") if isinstance(payload.get("refs"), list) else [],
                "updated_at": now_timestamp(),
            }
        )
        return state

    state = update_json_state(data_root, "state.json", _update, default={"schema_version": SCHEMA_VERSION, "skills": []})
    return {"view_filter": state["view_filter"]}



def clear_custom_view_payload(data_root: Path) -> dict:
    def _update(state: dict) -> dict:
        current = normalize_view_filter(state.get("view_filter"))
        state["schema_version"] = SCHEMA_VERSION
        state["skills"] = state.get("skills") if isinstance(state.get("skills"), list) else []
        state["view_filter"] = normalize_view_filter(
            {
                "mode": "search",
                "query": current.get("query"),
                "enabled": current.get("enabled"),
                "title": "",
                "refs": [],
                "updated_at": now_timestamp(),
            }
        )
        return state

    state = update_json_state(data_root, "state.json", _update, default={"schema_version": SCHEMA_VERSION, "skills": []})
    return {"view_filter": state["view_filter"]}



def skill_summary(item: dict) -> dict:
    skill_id = validate_skill_id(str(item.get("id") or ""))
    return {
        "id": skill_id,
        "local_id": skill_id,
        "name": normalize_title(str(item.get("name") or ""), skill_id, "name"),
        "description": normalize_description(str(item.get("description") or "")),
        "enabled": bool(item.get("enabled", True)),
        "created_at": str(item.get("created_at") or now_timestamp()),
        "updated_at": str(item.get("updated_at") or now_timestamp()),
        "origin": "workspace",
        "source_path": str(item.get("source_path") or ""),
        "editable": True,
        "deletable": True,
    }



def list_skills(data_root: Path) -> list[dict]:
    state = read_state(data_root)
    records_by_id: dict[str, dict] = {}
    for item in state["skills"]:
        summary = skill_summary(item)
        path = skill_dir(data_root, summary["id"])
        if not (path / "SKILL.md").is_file():
            continue
        if summary["id"] in records_by_id:
            continue
        parsed = parse_skill_markdown((path / "SKILL.md").read_text(encoding="utf-8"), skill_id=summary["id"], metadata=summary)
        summary = skill_summary(parsed)
        summary["source_path"] = str(path)
        records_by_id[summary["id"]] = summary
    for path in sorted(skills_root(data_root).iterdir()):
        if not path.is_dir() or not (path / "SKILL.md").is_file() or path.name in records_by_id:
            continue
        parsed = parse_skill_markdown((path / "SKILL.md").read_text(encoding="utf-8"), skill_id=path.name)
        summary = skill_summary(parsed)
        summary["source_path"] = str(path.resolve())
        records_by_id[summary["id"]] = summary
    records = list(records_by_id.values())
    records = sorted(records, key=lambda item: item["name"].casefold())
    write_state(data_root, records)
    return records



def get_skill(data_root: Path, skill_id: str) -> dict | None:
    normalized = validate_skill_id(skill_id)
    metadata = next((item for item in list_skills(data_root) if item["id"] == normalized), None)
    path = skill_file(data_root, normalized)
    if metadata is None or not path.is_file():
        return None
    return parse_skill_markdown(path.read_text(encoding="utf-8"), skill_id=normalized, metadata=metadata)



def save_skill(data_root: Path, payload: dict) -> dict:
    timestamp = now_timestamp()
    skill_id = validate_skill_id(str(payload.get("id") or ""))
    existing = get_skill(data_root, skill_id)
    candidate = {
        **(existing or {}),
        **payload,
        "created_at": (existing or {}).get("created_at") or timestamp,
        "updated_at": timestamp,
        "enabled": bool(payload.get("enabled", (existing or {}).get("enabled", True))),
    }
    path = skill_file(data_root, skill_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(skill_markdown(candidate), encoding="utf-8")
    summaries = [item for item in list_skills(data_root) if item["id"] != skill_id]
    saved_summary = skill_summary(candidate)
    summaries.append(saved_summary)
    write_state(data_root, sorted(summaries, key=lambda item: item["name"].casefold()))
    saved = get_skill(data_root, skill_id)
    if saved is None:
        raise SkillsValidationError(f"Skill `{skill_id}` was not saved.")
    return saved



def delete_skill(data_root: Path, skill_id: str) -> bool:
    normalized = validate_skill_id(skill_id)
    path = skill_file(data_root, normalized)
    existed = path.is_file()
    if existed:
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
    write_state(data_root, [item for item in list_skills(data_root) if item["id"] != normalized])
    return existed
