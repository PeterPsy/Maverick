"""Repository-level path discovery for Maverick v3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstallationPaths:
    """Canonical installation roots for a Maverick v3 checkout."""

    repository_root: Path
    core_root: Path
    apps_root: Path
    workspaces_root: Path
    logs_root: Path
    platform_logs_root: Path
    runtime_logs_root: Path
    docs_root: Path
    architecture_docs_root: Path
    local_skills_root: Path
    scripts_root: Path


def discover_repository_root(start_path: Path | None = None) -> Path:
    """Return the Maverick v3 repository root from any nested path."""
    current = (start_path or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    required_markers = {"AGENTS.md", "IMPLEMENTATION_TASKLIST.md", "core", "apps", "workspaces"}

    for candidate in (current, *current.parents):
        if required_markers.issubset({path.name for path in candidate.iterdir()}):
            return candidate

    raise FileNotFoundError("Could not locate the Maverick v3 repository root.")


def installation_paths(start_path: Path | None = None) -> InstallationPaths:
    """Build canonical installation paths for the active Maverick v3 checkout."""
    repository_root = discover_repository_root(start_path=start_path)
    docs_root = repository_root / "docs"
    logs_root = repository_root / "logs"
    return InstallationPaths(
        repository_root=repository_root,
        core_root=repository_root / "core",
        apps_root=repository_root / "apps",
        workspaces_root=repository_root / "workspaces",
        logs_root=logs_root,
        platform_logs_root=logs_root / "platform",
        runtime_logs_root=logs_root / "runtime",
        docs_root=docs_root,
        architecture_docs_root=docs_root / "architecture",
        local_skills_root=repository_root / "local-skills",
        scripts_root=repository_root / "scripts",
    )
