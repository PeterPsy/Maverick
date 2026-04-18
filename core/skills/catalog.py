"""Catalog builders for core-owned and app-contributed skill assets."""

from __future__ import annotations

from pathlib import Path

from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.store import AppStore
from core.shared.repository import installation_paths
from core.skills.models import SkillDefinition


def _iter_skill_roots(parent: Path) -> list[Path]:
    if not parent.exists():
        return []
    return sorted(
        [path for path in parent.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()],
        key=lambda item: item.name,
    )


def list_core_skills(*, start_path: Path | None = None) -> list[SkillDefinition]:
    """List repository-local core-owned skills."""
    paths = installation_paths(start_path=start_path)
    skills: list[SkillDefinition] = []
    for skill_root in _iter_skill_roots(paths.local_skills_root):
        skills.append(
            SkillDefinition(
                skill_id=f"core.{skill_root.name}",
                local_skill_id=skill_root.name,
                name=skill_root.name,
                description=f"Core skill `{skill_root.name}`.",
                source_root=str(skill_root.resolve()),
                owner_kind="core",
                owner_id="core",
                workspace_id=None,
                status="available",
            )
        )
    return skills


def list_workspace_app_skills(
    store: AppStore,
    *,
    workspace_id: str,
    start_path: Path | None = None,
) -> list[SkillDefinition]:
    """List visible app-contributed skill assets for one workspace."""
    skills: list[SkillDefinition] = []
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        if not parsed.contract.capabilities.skills:
            continue
        if parsed.contract.entrypoints.skills_root is None:
            raise ValueError(
                f"App `{parsed.app_id}` declares skills but no skills root in its contract."
            )
        skills_root = (source_root / parsed.contract.entrypoints.skills_root).resolve()
        if not skills_root.is_dir():
            raise ValueError(f"App `{parsed.app_id}` skills root `{skills_root}` does not exist.")
        for skill_id in parsed.contract.capabilities.skills:
            candidate_root = skills_root / skill_id
            if (candidate_root / "SKILL.md").is_file():
                resolved_root = candidate_root
            elif len(parsed.contract.capabilities.skills) == 1 and (skills_root / "SKILL.md").is_file():
                resolved_root = skills_root
            else:
                raise ValueError(
                    f"App `{parsed.app_id}` skill `{skill_id}` was declared but no matching SKILL.md was found."
                )
            skills.append(
                SkillDefinition(
                    skill_id=f"app.{parsed.app_id}.{skill_id}",
                    local_skill_id=skill_id,
                    name=skill_id,
                    description=f"App skill `{skill_id}` from `{parsed.app_id}`.",
                    source_root=str(resolved_root),
                    owner_kind="app",
                    owner_id=parsed.app_id,
                    workspace_id=workspace_id,
                    status="available",
                )
            )
    return skills


def list_visible_skills(
    *,
    app_store: AppStore | None = None,
    workspace_id: str | None = None,
    start_path: Path | None = None,
) -> list[SkillDefinition]:
    """List all visible skills for the requested workspace context."""
    skills = list_core_skills(start_path=start_path)
    if app_store is not None and workspace_id is not None:
        skills.extend(list_workspace_app_skills(app_store, workspace_id=workspace_id, start_path=start_path))
    seen: set[str] = set()
    for skill in skills:
        if skill.skill_id in seen:
            raise ValueError(f"Skill `{skill.skill_id}` is registered more than once.")
        seen.add(skill.skill_id)
    return sorted(skills, key=lambda item: (item.owner_kind, item.skill_id))
