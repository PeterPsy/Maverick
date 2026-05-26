"""Structured Calendar backend exceptions."""

from __future__ import annotations

from typing import Any


class CalendarConflictError(ValueError):
    """Raised when a mutating operation is blocked by scheduling conflicts."""

    def __init__(self, detail: str, conflicts: list[dict[str, Any]]) -> None:
        super().__init__(detail)
        self.conflicts = conflicts


class CalendarRevisionConflictError(ValueError):
    """Raised when an optimistic-concurrency revision check fails."""

    def __init__(
        self,
        detail: str,
        *,
        event_id: str,
        expected_revision: int,
        actual_revision: int,
        current_event: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.event_id = event_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        self.current_event = current_event
