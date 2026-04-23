"""Helpers for rebasing persisted repository-local absolute paths."""

from __future__ import annotations

import json
from pathlib import Path

from core.shared.repository import discover_repository_root


_REPOSITORY_ROOT_MARKERS = (
    ".maverick/local-state",
    "workspaces/",
    "apps/",
)


def rebase_repository_path(value: str, *, repository_root: Path) -> str:
    """Rebase one persisted absolute path into the current repository root when possible."""
    text = str(value).strip()
    if not text:
        return value
    try:
        candidate = Path(text)
    except OSError:
        return value
    if not candidate.is_absolute():
        return value

    normalized_repository_root = repository_root.resolve()
    if candidate == normalized_repository_root or normalized_repository_root in candidate.parents:
        return str(candidate)

    normalized_text = candidate.as_posix()
    for marker in _REPOSITORY_ROOT_MARKERS:
        marker_index = normalized_text.find(f"/{marker}")
        if marker_index == -1:
            continue
        relative_suffix = normalized_text[marker_index + 1 :]
        return str((normalized_repository_root / relative_suffix).resolve())
    return value


def _rewrite_documents(path: Path, *, fields: tuple[str, ...], repository_root: Path) -> bool:
    if not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return False
    changed = False
    for document in payload:
        if not isinstance(document, dict):
            continue
        for field in fields:
            value = document.get(field)
            if not isinstance(value, str):
                continue
            rebased = rebase_repository_path(value, repository_root=repository_root)
            if rebased != value:
                document[field] = rebased
                changed = True
    if changed:
        path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return changed


def rebase_local_state_paths(*, start_path: Path | None = None) -> list[Path]:
    """Rebase all known local-state path fields to the current repository root."""
    repository_root = discover_repository_root(start_path=start_path)
    changed_paths: list[Path] = []

    targets = [
        (repository_root / ".maverick" / "local-state" / "apps" / "app_sources.json", ("source_path",)),
        (
            repository_root / ".maverick" / "local-state" / "apps" / "workspace_local_app_projects.json",
            ("project_root",),
        ),
        (repository_root / ".maverick" / "local-state" / "apps" / "workspace_app_bindings.json", ("data_root",)),
    ]
    for path in sorted((repository_root / "workspaces").glob("*/data/skills/state.json")):
        targets.append((path, ("source_path",)))

    for path, fields in targets:
        if _rewrite_documents(path, fields=fields, repository_root=repository_root):
            changed_paths.append(path)
    return changed_paths
