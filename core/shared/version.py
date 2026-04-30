"""Version helpers for the Maverick repository."""

from __future__ import annotations

from pathlib import Path
import tomllib

from core.shared.repository import installation_paths


def current_core_version(start_path: Path | None = None) -> str:
    """Return the canonical core version from project metadata."""
    pyproject = installation_paths(start_path=start_path).repository_root / "pyproject.toml"
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(payload["project"]["version"])
