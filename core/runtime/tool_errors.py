"""Normalized fail-closed errors for runtime tool orchestration."""


class RuntimeToolError(RuntimeError):
    """Base error with a stable machine-readable reason code."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code


class RuntimeToolRevisionError(RuntimeToolError):
    """A persisted tool or grant revision was stale."""


class RuntimeToolSchemaError(RuntimeToolError):
    """A schema or provider argument payload was invalid."""
