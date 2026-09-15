"""Agents has no bundled catalog; only initialize its empty store."""

from __future__ import annotations

from pathlib import Path

from store import ensure_data_root, list_agent_definitions


def seed_defaults(data_root: Path) -> dict[str, int]:
    ensure_data_root(data_root)
    return {"agent_count": len(list_agent_definitions(data_root))}
