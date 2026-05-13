"""Storage app errors."""

from __future__ import annotations


class StorageValidationError(ValueError):
    """Raised when storage input cannot be accepted."""
