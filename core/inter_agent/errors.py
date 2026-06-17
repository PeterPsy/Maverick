"""Inter-agent domain errors."""

from __future__ import annotations


class InterAgentError(Exception):
    """Base error for inter-agent domain failures."""


class InterAgentValidationError(InterAgentError, ValueError):
    """Raised when an inter-agent specification violates core invariants."""


class InterAgentIdempotencyConflictError(InterAgentValidationError):
    """Raised when an idempotent retry reuses a key with a different payload."""


class InterAgentRunNotFoundError(InterAgentError, LookupError):
    """Raised when an inter-agent run cannot be found."""


class InterAgentParticipantNotFoundError(InterAgentError, LookupError):
    """Raised when an inter-agent participant cannot be found."""


class InterAgentEdgeNotFoundError(InterAgentError, LookupError):
    """Raised when an inter-agent edge cannot be found."""


class InterAgentApprovalNotFoundError(InterAgentError, LookupError):
    """Raised when an inter-agent approval request cannot be found."""


class InterAgentBudgetPolicyNotFoundError(InterAgentError, LookupError):
    """Raised when an inter-agent budget policy cannot be found."""


class InterAgentBudgetLedgerNotFoundError(InterAgentError, LookupError):
    """Raised when an inter-agent budget ledger cannot be found."""


class InterAgentBudgetExceededError(InterAgentValidationError):
    """Raised when a budget reservation would exceed the run policy."""


class InterAgentEventNotFoundError(InterAgentError, LookupError):
    """Raised when an inter-agent event cursor cannot be resolved."""


class InterAgentOperationError(InterAgentError):
    """Raised when an inter-agent runtime operation cannot be completed."""
