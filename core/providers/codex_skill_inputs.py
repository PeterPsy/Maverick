"""Build fail-closed Codex UserInput items for explicitly invoked skills."""

from __future__ import annotations

from pathlib import Path

from core.providers.errors import ProviderLaunchError
from core.skills.models import SkillDefinition


def codex_skill_input_items(
    runtime_root: str | Path,
    invoked_skills: list[SkillDefinition] | None,
) -> list[dict[str, str]]:
    """Resolve invoked skills only from the materialized Codex runtime home."""
    if not invoked_skills:
        return []
    runtime_home = Path(runtime_root) / "codex-home"
    skills_root = runtime_home / "skills"
    try:
        resolved_runtime_home = runtime_home.resolve(strict=True)
        resolved_skills_root = skills_root.resolve(strict=True)
    except OSError as error:
        raise ProviderLaunchError("invoked_skill_runtime_path_missing") from error
    if not resolved_skills_root.is_relative_to(resolved_runtime_home):
        raise ProviderLaunchError("invoked_skill_runtime_path_unsafe")

    items: list[dict[str, str]] = []
    for skill in invoked_skills:
        parts = _safe_skill_parts(skill.skill_id)
        target_root = skills_root.joinpath(*parts)
        skill_file = target_root / "SKILL.md"
        try:
            resolved_target_root = target_root.resolve(strict=True)
            resolved_skill_file = skill_file.resolve(strict=True)
        except OSError as error:
            raise ProviderLaunchError("invoked_skill_runtime_path_missing") from error
        if target_root.is_symlink() or skill_file.is_symlink():
            raise ProviderLaunchError("invoked_skill_runtime_path_unsafe")
        if not resolved_target_root.is_dir() or not resolved_skill_file.is_file():
            raise ProviderLaunchError("invoked_skill_runtime_path_invalid")
        if not resolved_target_root.is_relative_to(resolved_skills_root):
            raise ProviderLaunchError("invoked_skill_runtime_path_unsafe")
        if not resolved_skill_file.is_relative_to(resolved_target_root):
            raise ProviderLaunchError("invoked_skill_runtime_path_unsafe")
        items.append(
            {
                "type": "skill",
                "name": skill.skill_id,
                "path": str(resolved_skill_file),
            }
        )
    return items


def _safe_skill_parts(skill_id: str) -> tuple[str, ...]:
    parts = tuple(part for part in str(skill_id or "").strip().split(".") if part)
    if not parts or any(part in {".", "..", ".system"} or "/" in part or "\\" in part for part in parts):
        raise ProviderLaunchError("invalid_invoked_skill_id")
    return parts


__all__ = ["codex_skill_input_items"]
