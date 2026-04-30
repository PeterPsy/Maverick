"""Secret-domain errors."""

from __future__ import annotations


class SecretError(RuntimeError):
    """Base error for secret-domain failures."""


class SecretNotFoundError(SecretError):
    """Raised when secret metadata cannot be found."""


class SecretBindingError(SecretError):
    """Raised when secret binding state is invalid."""


class SecretResolutionError(SecretError):
    """Raised when a secret cannot be resolved safely."""


class SecretPolicyError(SecretError):
    """Raised when secret access violates platform policy."""
