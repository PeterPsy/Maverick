"""Storage app errors."""

from __future__ import annotations

from typing import Any


class StorageValidationError(ValueError):
    """Raised when storage input cannot be accepted."""

    def __init__(
        self,
        detail: str,
        *,
        operation: str = "",
        expected_fields: list[str] | None = None,
        accepted_aliases: dict[str, list[str]] | None = None,
        allowed_values: dict[str, list[str]] | None = None,
        example: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.operation = operation
        self.expected_fields = expected_fields or []
        self.accepted_aliases = accepted_aliases or {}
        self.allowed_values = allowed_values or {}
        self.example = example or {}


def validation_error_payload(error: StorageValidationError) -> dict[str, Any]:
    """Return a machine-correctable validation error payload."""
    payload: dict[str, Any] = {
        "error": "validation_error",
        "detail": error.detail,
    }
    if error.operation:
        payload["operation"] = error.operation
    if error.expected_fields:
        payload["expected_fields"] = error.expected_fields
    if error.accepted_aliases:
        payload["accepted_aliases"] = error.accepted_aliases
    if error.allowed_values:
        payload["allowed_values"] = error.allowed_values
    if error.example:
        payload["example"] = error.example
    return payload
