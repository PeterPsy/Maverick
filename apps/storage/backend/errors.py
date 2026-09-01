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


class StorageConflictError(RuntimeError):
    """Raised when a guarded Storage mutation no longer matches current state."""

    def __init__(
        self,
        detail: str,
        *,
        conflict: str,
        expected_sha256: str = "",
        current_sha256: str = "",
        replacement_index: int | None = None,
        expected_occurrences: int | None = None,
        actual_occurrences: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.conflict = conflict
        self.expected_sha256 = expected_sha256
        self.current_sha256 = current_sha256
        self.replacement_index = replacement_index
        self.expected_occurrences = expected_occurrences
        self.actual_occurrences = actual_occurrences


class StorageAuthorizationError(PermissionError):
    """Raised when an authenticated actor lacks authority for an operation."""

    def __init__(self, detail: str, *, operation: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.operation = operation


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


def conflict_error_payload(error: StorageConflictError) -> dict[str, Any]:
    """Return a machine-readable optimistic concurrency conflict."""
    payload: dict[str, Any] = {
        "error": "conflict",
        "conflict": error.conflict,
        "detail": error.detail,
    }
    if error.expected_sha256:
        payload["expected_sha256"] = error.expected_sha256
    if error.current_sha256:
        payload["current_sha256"] = error.current_sha256
    if error.replacement_index is not None:
        payload["replacement_index"] = error.replacement_index
    if error.expected_occurrences is not None:
        payload["expected_occurrences"] = error.expected_occurrences
    if error.actual_occurrences is not None:
        payload["actual_occurrences"] = error.actual_occurrences
    return payload


def authorization_error_payload(error: StorageAuthorizationError) -> dict[str, Any]:
    """Return a redaction-safe authorization error payload."""
    payload = {"error": "forbidden", "detail": error.detail}
    if error.operation:
        payload["operation"] = error.operation
    return payload
