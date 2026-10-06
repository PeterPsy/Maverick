"""Bounded inputs for Browser's fixed page-reading operations."""

from __future__ import annotations

import math
from typing import Any

from errors import BrowserValidationError


READING_ACTION_FIELDS = {
    "content.read": frozenset({"action", "session_id", "max_chars", "max_items"}),
    "scroll": frozenset({"action", "session_id", "direction", "pixels", "steps", "settle_ms"}),
    "video.frame": frozenset({"action", "session_id", "video_index", "time_seconds"}),
}


def validate_reading_action(action: str, body: dict[str, Any]) -> None:
    if action == "content.read":
        _integer(body, "max_chars", 1, 100_000)
        _integer(body, "max_items", 1, 200)
    elif action == "scroll":
        if body.get("direction", "down") not in ("up", "down"):
            raise BrowserValidationError("direction must be up or down.", field="direction")
        _integer(body, "pixels", 1, 2000)
        _integer(body, "steps", 1, 5)
        _integer(body, "settle_ms", 0, 1500)
    elif action == "video.frame":
        _integer(body, "video_index", 0, 199)
        value = body.get("time_seconds")
        if "time_seconds" in body and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 86_400
        ):
            raise BrowserValidationError(
                "time_seconds must be a finite number between 0 and 86400.",
                field="time_seconds",
            )


def _integer(body: dict[str, Any], field: str, minimum: int, maximum: int) -> None:
    if field not in body:
        return
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BrowserValidationError(
            f"{field} must be an integer between {minimum} and {maximum}.", field=field
        )
