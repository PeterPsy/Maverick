"""Shared constants and naming helpers for app contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re



CURRENT_APP_CONTRACT_VERSION = "1.0"
APP_CONTRACT_FILENAME = "app_contract.json"
APP_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)

def _timestamp(now: datetime | None = None) -> str:
    return (now or utcnow()).isoformat()

def _normalize_slug(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")
    return normalized or fallback

def app_contract_path(source_root: Path) -> Path:
    """Return the canonical contract-file path for one app root."""
    return source_root / APP_CONTRACT_FILENAME
