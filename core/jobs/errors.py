"""Typed errors for durable compute jobs."""


class JobError(Exception):
    """Base error for the durable job domain."""


class JobValidationError(JobError):
    """Raised when a protocol record is invalid."""


class JobAuthorizationError(JobError):
    """Raised when a trusted caller lacks authority for a job operation."""


class JobNotFoundError(JobError):
    """Raised when a workspace-scoped job cannot be found."""


class JobIdempotencyConflictError(JobError):
    """Raised when an idempotency key is reused for a different spec."""


class JobTransitionError(JobError):
    """Raised when a state transition is not permitted."""


class JobConcurrencyError(JobError):
    """Raised when an atomic mutation loses its compare-and-set fence."""


class JobLeaseError(JobError):
    """Raised when a caller does not own the current lease."""


class JobQuotaExceededError(JobError):
    """Raised when a workspace job quota would be exceeded."""


class ExecutorNotFoundError(JobError):
    """Raised when an executor advertisement cannot be found."""


class ExecutorCompatibilityError(JobError):
    """Raised when no compatible executor or handler is available."""


class JobHandlerError(JobError):
    """Redaction-safe handler failure with explicit retry semantics."""

    def __init__(self, error_code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.safe_message = message
        self.retryable = retryable


class JobCancelledError(JobError):
    """Raised by a cooperative handler after observing cancellation."""
