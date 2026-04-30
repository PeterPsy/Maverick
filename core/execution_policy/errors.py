"""Execution-policy errors."""


class ExecutionPolicyError(ValueError):
    """Base error for execution-policy operations."""


class UnsupportedExecutionModeError(ExecutionPolicyError):
    """Raised when an unsupported execution mode is requested."""


class WorkspaceExecutionBoundaryError(ExecutionPolicyError):
    """Raised when runtime boundary enforcement fails."""
