"""Runtime-domain errors."""

from __future__ import annotations


class RuntimeDomainError(Exception):
    """Base error for runtime-domain failures."""


class RuntimeSessionNotFoundError(RuntimeDomainError):
    """Raised when one runtime session record is missing."""


class RuntimeTurnNotFoundError(RuntimeDomainError):
    """Raised when one runtime turn record is missing."""


class RuntimeProcessNotFoundError(RuntimeDomainError):
    """Raised when one runtime process record is missing."""


class RuntimeStateNotFoundError(RuntimeDomainError):
    """Raised when one runtime state record is missing."""


class RuntimeThreadNotFoundError(RuntimeDomainError):
    """Raised when one core-owned runtime thread record is missing."""


class RuntimeTransitionError(RuntimeDomainError):
    """Raised when one runtime lifecycle transition is invalid."""
