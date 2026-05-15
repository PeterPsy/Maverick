"""Chat app structured errors."""

from __future__ import annotations

from typing import Any


class ChatValidationError(ValueError):
    """Structured validation error for Chat app operations."""

    def __init__(
        self,
        detail: str,
        *,
        expected_fields: list[str] | None = None,
        accepted_aliases: dict[str, list[str]] | None = None,
        allowed_values: dict[str, list[str]] | None = None,
        example: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.expected_fields = expected_fields or []
        self.accepted_aliases = accepted_aliases or {}
        self.allowed_values = allowed_values or {}
        self.example = example or {}
