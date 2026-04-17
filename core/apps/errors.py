"""App-hosting domain errors."""

from __future__ import annotations


class AppHostingError(Exception):
    """Base error for the app-hosting domain."""


class AppSourceNotFoundError(AppHostingError):
    """Raised when an installation-level app source is missing."""


class WorkspaceLocalAppProjectNotFoundError(AppHostingError):
    """Raised when a workspace-local app project is missing."""


class WorkspaceAppBindingNotFoundError(AppHostingError):
    """Raised when a workspace app binding is missing."""


class AppCompatibilityError(AppHostingError):
    """Raised when an app source is not compatible with the requested install target."""


class AppLifecycleError(AppHostingError):
    """Raised when an app lifecycle transition is invalid."""


class AppDataRootError(AppHostingError):
    """Raised when app-owned workspace data cannot be prepared safely."""
