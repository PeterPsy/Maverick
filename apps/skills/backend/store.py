"""JSON and markdown-backed storage for workspace-owned skills."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
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
    if payload.get("schema_version") != SCHEMA_VERSION:
        payload["schema_version"] = SCHEMA_VERSION
    skills = payload.get("skills") if isinstance(payload.get("skills"), list) else []
    payload["skills"] = [item for item in skills if isinstance(item, dict)]
    return payload


def write_state(data_root: Path, skills: list[dict]) -> None:
    write_json(state_path(data_root), {"schema_version": SCHEMA_VERSION, "skills": skills})


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
    records = []
    for item in state["skills"]:
        summary = skill_summary(item)
        summary["source_path"] = str(skill_dir(data_root, summary["id"]))
        records.append(summary)
    existing_ids = {item["id"] for item in records}
    for path in sorted(skills_root(data_root).iterdir()):
        if not path.is_dir() or not (path / "SKILL.md").is_file() or path.name in existing_ids:
            continue
        parsed = parse_skill_markdown((path / "SKILL.md").read_text(encoding="utf-8"), skill_id=path.name)
        summary = skill_summary(parsed)
        summary["source_path"] = str(path.resolve())
        records.append(summary)
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
