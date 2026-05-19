"""Speech app error types."""

from __future__ import annotations


class SpeechValidationError(ValueError):
    """Raised when a Speech backend request is invalid."""

    def __init__(
        self,
        message: str,
        *,
        operation: str = "synthesize",
        expected_fields: list[str] | None = None,
        allowed_values: dict[str, list[str]] | None = None,
        example: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.expected_fields = expected_fields or []
        self.allowed_values = allowed_values or {}
        self.example = example or {}


class SpeechProviderUnavailableError(RuntimeError):
    """Raised when no configured local synthesis engine is available."""


def validation_error_payload(error: SpeechValidationError) -> dict:
    payload = {
        "error": "validation_error",
        "operation": error.operation,
        "detail": str(error),
    }
    if error.expected_fields:
        payload["expected_fields"] = error.expected_fields
    if error.allowed_values:
        payload["allowed_values"] = error.allowed_values
    if error.example:
        payload["example"] = error.example
    return payload
