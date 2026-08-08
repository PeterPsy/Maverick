"""Transport-neutral application facade for Video Studio foundation actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from foundation.service import FOUNDATION_ACTIONS, FoundationService, FoundationServiceError


def handle_foundation_action(
    data_root: str | Path,
    action: str,
) -> tuple[int, dict[str, Any]]:
    """Dispatch one bounded action with a stable transport-neutral envelope."""
    normalized = str(action or "status").strip().lower()
    if normalized not in FOUNDATION_ACTIONS:
        return 400, {
            "ok": False,
            "error": {
                "code": "unsupported_action",
                "message": f"Unsupported foundation action `{normalized}`.",
            },
        }
    try:
        result = FoundationService(data_root).dispatch(normalized)
    except FoundationServiceError as error:
        return 503, {
            "ok": False,
            "error": {"code": "foundation_unavailable", "message": str(error)},
        }
    return 200, {"ok": True, **result}
