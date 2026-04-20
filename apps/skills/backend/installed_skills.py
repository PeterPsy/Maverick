"""Discovery for Codex skills installed in the host agent environment."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import re

from store import SkillsValidationError, normalize_description, normalize_title, parse_skill_markdown, skill_markdown


def installed_skill_roots(agent_skill_roots: list[str] | None = None) -> list[Path]:
    roots = [Path(item).expanduser() for item in agent_skill_roots or [] if str(item).strip()]
    if roots:
        return roots
    codex_home = Path.home() / ".codex"
    return [codex_home / "skills", codex_home / "plugins" / "cache"]


def list_installed_agent_skills(agent_skill_roots: list[str] | None = None) -> list[dict]:
    records: list[dict] = []
    seen_paths: set[Path] = set()
    seen_ids: set[str] = set()
    for root in installed_skill_roots(agent_skill_roots):
        for skill_root in _discover_skill_roots(root):
            resolved = skill_root.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                record = _installed_skill_summary(skill_root)
            except SkillsValidationError:
                continue
            skill_id = _unique_skill_id(record["id"], seen_ids)
            record["id"] = skill_id
            seen_ids.add(skill_id)
            records.append(record)
    return sorted(records, key=lambda item: (item["origin"], item["name"].casefold(), item["id"]))


def get_installed_agent_skill(skill_id: str, agent_skill_roots: list[str] | None = None) -> dict | None:
    normalized = str(skill_id or "").strip()
    for summary in list_installed_agent_skills(agent_skill_roots):
        if summary["id"] != normalized:
            continue
        path = Path(summary["source_path"]) / "SKILL.md"
        if not path.is_file():
            return None
        parsed = parse_skill_markdown(path.read_text(encoding="utf-8"), skill_id=summary["local_id"], metadata=summary)
        parsed.update(
            {
                "id": summary["id"],
                "local_id": summary["local_id"],
                "origin": summary["origin"],
                "source_path": summary["source_path"],
                "editable": summary["editable"],
                "deletable": False,
                "enabled": True,
            }
        )
        return parsed
    return None


def save_installed_agent_skill(skill_id: str, payload: dict, agent_skill_roots: list[str] | None = None) -> dict | None:
    existing = get_installed_agent_skill(skill_id, agent_skill_roots)
    if existing is None:
        return None
    markdown_path = Path(existing["source_path"]) / "SKILL.md"
    if not markdown_path.is_file():
        raise SkillsValidationError(f"Installed skill `{skill_id}` has no SKILL.md file.")
    if not existing.get("editable"):
        raise SkillsValidationError(f"Installed skill `{skill_id}` is not writable by this host.")
    candidate = {
        "id": existing["local_id"],
        "name": payload.get("name", existing["name"]),
        "description": payload.get("description", existing["description"]),
        "content": payload.get("content", existing["content"]),
    }
    markdown_path.write_text(skill_markdown(candidate), encoding="utf-8")
    updated = get_installed_agent_skill(skill_id, agent_skill_roots)
    if updated is None:
        raise SkillsValidationError(f"Installed skill `{skill_id}` was not saved.")
    return updated


def _discover_skill_roots(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if (root / "SKILL.md").is_file():
        return [root]
    roots: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if (child / "SKILL.md").is_file():
            roots.append(child)
        if child.name == ".system" and child.is_dir():
            roots.extend(
                sorted(
                    [system_child for system_child in child.iterdir() if (system_child / "SKILL.md").is_file()],
                    key=lambda item: item.name,
                )
            )
    for path in root.rglob("SKILL.md"):
        if "node_modules" in path.parts:
            continue
        parent = path.parent
        if _is_codex_skill_root(root, parent):
            roots.append(parent)
    seen: set[str] = set()
    unique_roots: list[Path] = []
    for skill_root in roots:
        key = str(skill_root)
        if key not in seen:
            seen.add(key)
            unique_roots.append(skill_root)
    return sorted(unique_roots, key=lambda item: str(item))


def _is_codex_skill_root(search_root: Path, skill_root: Path) -> bool:
    relative_parts = skill_root.absolute().relative_to(search_root.absolute()).parts
    if not relative_parts:
        return True
    if search_root.name == "skills":
        return len(relative_parts) <= 2
    return len(relative_parts) >= 2 and relative_parts[-2] == "skills"


def _installed_skill_summary(skill_root: Path) -> dict:
    markdown_path = skill_root / "SKILL.md"
    local_id = skill_root.name
    parsed = parse_skill_markdown(markdown_path.read_text(encoding="utf-8"), skill_id=local_id)
    stat = markdown_path.stat()
    timestamp = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    origin = _origin_for_skill(skill_root)
    return {
        "id": _catalog_id(origin, local_id),
        "local_id": local_id,
        "name": normalize_title(str(parsed.get("name") or ""), local_id, "name"),
        "description": normalize_description(str(parsed.get("description") or "")),
        "enabled": True,
        "created_at": timestamp,
        "updated_at": timestamp,
        "origin": origin,
        "source_path": str(skill_root.resolve()),
        "editable": _is_writable_skill(markdown_path),
        "deletable": False,
    }


def _origin_for_skill(skill_root: Path) -> str:
    parts = skill_root.resolve().parts
    if ".system" in parts:
        return "codex-system"
    if "plugins" in parts and "cache" in parts:
        return "codex-plugin"
    return "codex-installed"


def _catalog_id(origin: str, local_id: str) -> str:
    return f"{origin}-{_slug(local_id)}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "skill"


def _unique_skill_id(skill_id: str, seen_ids: set[str]) -> str:
    candidate = skill_id
    suffix = 2
    while candidate in seen_ids:
        candidate = f"{skill_id}-{suffix}"
        suffix += 1
    return candidate


def _is_writable_skill(markdown_path: Path) -> bool:
    return markdown_path.is_file() and os.access(markdown_path, os.W_OK)
