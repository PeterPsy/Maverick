"""Catalog builders for workspace-owned runtime skill assets."""

from __future__ import annotations

import json
from pathlib import Path

from core.skills.models import SkillDefinition
from core.apps.paths import workspace_app_data_root


def workspace_skills_data_root(workspace_id: str, start_path: Path | None = None) -> Path:
    """Return the Skills app data root for one workspace."""
    return workspace_app_data_root(workspace_id=workspace_id, app_id="skills", start_path=start_path)


def workspace_skills_root(workspace_id: str, start_path: Path | None = None) -> Path:
    """Return the workspace-owned skill directory for one workspace."""
    return workspace_skills_data_root(workspace_id=workspace_id, start_path=start_path) / "skills"


def list_workspace_skills(*, workspace_id: str, start_path: Path | None = None) -> list[SkillDefinition]:
    """List enabled workspace-owned skills available to Codex runtimes."""
    root = workspace_skills_root(workspace_id=workspace_id, start_path=start_path)
    if not root.exists():
        return []
    metadata = _workspace_skill_metadata(workspace_id=workspace_id, start_path=start_path)
    skills: list[SkillDefinition] = []
    for skill_root in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda item: item.name):
        skill_file = skill_root / "SKILL.md"
        if not skill_file.is_file():
            continue
        item_metadata = metadata.get(skill_root.name, {})
        if item_metadata and not bool(item_metadata.get("enabled", True)):
            continue
        frontmatter = _read_skill_frontmatter(skill_file)
        skills.append(
            SkillDefinition(
                skill_id=skill_root.name,
                local_skill_id=skill_root.name,
                name=str(item_metadata.get("name") or frontmatter.get("name") or skill_root.name),
                description=str(
                    item_metadata.get("description")
                    or frontmatter.get("description")
                    or f"Workspace skill `{skill_root.name}`."
                ),
                source_root=str(skill_root.resolve()),
                owner_kind="workspace",
                owner_id=workspace_id,
                workspace_id=workspace_id,
                status="available",
            )
        )
    return skills


def resolve_workspace_skills(
    *,
    workspace_id: str,
    skill_ids: list[str],
    start_path: Path | None = None,
) -> list[SkillDefinition]:
    """Resolve explicit skill ids from the workspace-owned skill catalog."""
    requested: list[str] = []
    seen: set[str] = set()
    for skill_id in skill_ids:
        normalized = str(skill_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        requested.append(normalized)
    available = {skill.skill_id: skill for skill in list_workspace_skills(workspace_id=workspace_id, start_path=start_path)}
    missing = [skill_id for skill_id in requested if skill_id not in available]
    if missing:
        raise ValueError(f"Unknown workspace skill ids for workspace `{workspace_id}`: {', '.join(missing)}")
    return [available[skill_id] for skill_id in requested]


def _workspace_skill_metadata(*, workspace_id: str, start_path: Path | None = None) -> dict[str, dict]:
    state_path = workspace_skills_data_root(workspace_id=workspace_id, start_path=start_path) / "state.json"
    if not state_path.is_file():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    skills = payload.get("skills") if isinstance(payload, dict) else None
    if not isinstance(skills, list):
        return {}
    metadata: dict[str, dict] = {}
    for item in skills:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            metadata[item["id"]] = item
    return metadata


def _read_skill_frontmatter(skill_file: Path) -> dict[str, str]:
    raw = skill_file.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        return {}
    try:
        _prefix, remainder = raw.split("---\n", 1)
        header, _body = remainder.split("\n---\n", 1)
    except ValueError:
        return {}
    fields: dict[str, str] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields
