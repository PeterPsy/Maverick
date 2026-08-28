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


class RuntimeSessionHiddenError(RuntimeDomainError):
    """Raised when a hidden runtime session is used as a user-visible thread."""


class RuntimeTranscriptAccessError(RuntimeDomainError):
    """Raised when a transcript read cannot be authorized or resolved safely."""

    def __init__(self, reason: str, *, status_code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class RuntimeTranscriptValidationError(RuntimeDomainError):
    """Raised when transcript pagination or window arguments are invalid."""


class RuntimeTransitionError(RuntimeDomainError):
    """Raised when one runtime lifecycle transition is invalid."""


class RuntimeTurnQueueRejectedError(RuntimeTransitionError):
    """Raised when authoritative session state rejects a new queued turn."""

    def __init__(self, message: str, *, reason_code: str = "runtime_session_not_executable") -> None:
        self.reason_code = reason_code
        super().__init__(message)


class RuntimeProviderStateError(RuntimeDomainError):
    """Raised when provider state is missing, stale, or invalid."""


class RuntimeToolExecutionLeaseExpiredError(RuntimeProviderStateError):
    """Raised when a tool result tries to commit after its execution lease."""


class RuntimeProfileUpgradeRequiredError(RuntimeDomainError):
    """Raised before admission when a pinned session cannot execute safely."""

    def __init__(self, reason_code: str, *, detail_code: str | None = None) -> None:
        self.reason_code = str(reason_code or "runtime_profile_upgrade_required")
        self.detail_code = str(detail_code or self.reason_code)
        super().__init__(self.reason_code)
