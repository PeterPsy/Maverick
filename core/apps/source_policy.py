"""Shared source-tree copy/package exclusion policy for Maverick apps."""

from __future__ import annotations

from pathlib import Path


EXCLUDED_SOURCE_NAMES = {
    ".git",
    ".hg",
    ".maverick",
    ".svn",
    "__pycache__",
    "logs",
    ".pytest_cache",
    "node_modules",
    "runtime",
    "storage",
    "secrets",
    "tmp",
}
EXCLUDED_SOURCE_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".duckdb", ".db", ".pem", ".key"}
EXCLUDED_SOURCE_FILENAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}


def is_excluded_app_source_path(path: Path, *, root: Path) -> bool:
    """Return whether a path should be excluded from app source artifacts."""
    relative = path.relative_to(root)
    if path.is_symlink():
        return True
    if any(part in EXCLUDED_SOURCE_NAMES for part in relative.parts):
        return True
    return path.name in EXCLUDED_SOURCE_FILENAMES or path.suffix in EXCLUDED_SOURCE_SUFFIXES


def ignored_app_source_names(directory: str, names: list[str]) -> set[str]:
    """Return names that must not be copied into promoted app source."""
    base = Path(directory)
    ignored: set[str] = set()
    for name in names:
        candidate = base / name
        if name in EXCLUDED_SOURCE_NAMES or name in EXCLUDED_SOURCE_FILENAMES or candidate.suffix in EXCLUDED_SOURCE_SUFFIXES:
            ignored.add(name)
            continue
        if candidate.is_symlink():
            ignored.add(name)
    return ignored
