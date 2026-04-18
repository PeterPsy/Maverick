"""Workspace-domain errors for filesystem and bootstrap operations."""


class WorkspaceError(ValueError):
    """Base error for workspace operations."""


class InvalidWorkspaceIdError(WorkspaceError):
    """Raised when a workspace identifier violates the filesystem contract."""


class WorkspaceNotFoundError(WorkspaceError):
    """Raised when a workspace cannot be resolved."""


class WorkspaceMembershipError(WorkspaceError):
    """Raised when workspace membership is missing or invalid."""


class WorkspaceGovernanceError(WorkspaceError):
    """Raised when a governance policy blocks an operation."""


class WorkspaceQuotaExceededError(WorkspaceError):
    """Raised when a workspace exceeds an operational limit."""


class WorkspaceExportError(WorkspaceError):
    """Raised when workspace export coordination fails."""
