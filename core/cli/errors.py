"""CLI-domain errors."""

from __future__ import annotations


class CliError(Exception):
    """Base error for the CLI domain."""


class CliCommandNotFoundError(CliError):
    """Raised when a requested CLI command is not registered."""


class CliInvocationNotAllowedError(CliError):
    """Raised when policy denies one CLI invocation."""
