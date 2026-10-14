"""Installation-owned provider login locations, separate from operator authority."""

from pathlib import Path
import os

from core.shared.repository import discover_repository_root


def codex_source_home() -> Path:
    configured = os.environ.get("LOOPINO_CODEX_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return discover_repository_root() / "data/provider-auth/codex"


def antigravity_source_home() -> Path:
    return discover_repository_root() / "data/provider-auth/antigravity"
