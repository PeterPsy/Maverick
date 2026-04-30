"""Seed workspace-owned skills from bundled Maverick skill templates."""

from __future__ import annotations

from pathlib import Path
import shutil

from store import ensure_data_root, skill_dir


def source_skill_roots(repository_root: Path) -> list[Path]:
    """Return bundled skill template roots that should be copied into a workspace."""
    roots: list[Path] = []
    apps_root = repository_root / "apps"
    if apps_root.is_dir():
        for app_root in sorted(path for path in apps_root.iterdir() if path.is_dir()):
            roots.extend(_direct_skill_roots(app_root / "skills"))
    return sorted(roots, key=lambda item: item.name)


def seed_default_skills(data_root: Path, *, repository_root: Path) -> list[str]:
    """Copy bundled skill templates into workspace-owned Skills app data."""
    ensure_data_root(data_root)
    seeded: list[str] = []
    for source_root in source_skill_roots(repository_root):
        target_root = skill_dir(data_root, source_root.name)
        if (target_root / "SKILL.md").is_file():
            _copy_missing_template_files(source_root, target_root)
            continue
        target_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_root, target_root)
        seeded.append(source_root.name)
    return seeded


def _copy_missing_template_files(source_root: Path, target_root: Path) -> None:
    for source_path in source_root.rglob("*"):
        if source_path.is_dir():
            continue
        relative_path = source_path.relative_to(source_root)
        target_path = target_root / relative_path
        if target_path.exists():
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def _direct_skill_roots(parent: Path) -> list[Path]:
    if not parent.is_dir():
        return []
    return sorted([path for path in parent.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()], key=lambda item: item.name)
