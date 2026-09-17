"""Canonical Codex conversation-home ownership."""

from __future__ import annotations

from pathlib import Path

from core.runtime.runtime_session import RuntimeSessionRecord


def resolve_codex_runtime_home(session: RuntimeSessionRecord) -> Path:
    """Return the private Codex home owned by this session."""
    return Path(session.runtime_root) / "codex-home"
