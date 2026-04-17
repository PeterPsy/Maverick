"""Workspace-domain errors for filesystem and bootstrap operations."""


class WorkspaceError(ValueError):
    """Base error for workspace operations."""


class InvalidWorkspaceIdError(WorkspaceError):
    """Raised when a workspace identifier violates the filesystem contract."""

