"""Errors shared by runtime cleanup orchestration helpers."""


class RuntimeCleanupError(Exception):
    """Raised when one full runtime cleanup cannot complete."""
