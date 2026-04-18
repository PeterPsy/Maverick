"""Recovery-domain errors."""

from __future__ import annotations


class RecoveryError(RuntimeError):
    """Base error for recovery-domain failures."""


class RecoveryFailureNotFoundError(RecoveryError):
    """Raised when one stored failure record cannot be found."""


class RecoveryIntentNotFoundError(RecoveryError):
    """Raised when one stored recovery intent cannot be found."""


class RecoveryHealthResultNotFoundError(RecoveryError):
    """Raised when one stored health result cannot be found."""
