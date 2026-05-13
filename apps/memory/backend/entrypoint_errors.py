"""Entrypoint-safe error handling helpers for Memory."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any


LOGGER = logging.getLogger("maverick.memory")
SENSITIVE_ERROR_MARKERS = ("secret", "token", "password", "authorization", "raw_value")


def storage_error_response(
    error: sqlite3.Error,
    *,
    app_id: str = "memory",
    action: str = "",
) -> tuple[int, dict[str, Any]]:
    LOGGER.error(
        json.dumps(
            {
                "event": "memory_storage_error",
                "app_id": app_id,
                "action": action,
                "error_type": type(error).__name__,
                "detail": safe_storage_detail(str(error)),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 500, {"error": "storage_error", "detail": "Memory storage operation failed."}


def safe_storage_detail(detail: str, *, max_chars: int = 300) -> str:
    text = " ".join(str(detail or "").split())
    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_ERROR_MARKERS):
        return "[redacted]"
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text or "sqlite_error"
