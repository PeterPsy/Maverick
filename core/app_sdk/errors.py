"""Errors raised by the Maverick app SDK."""

from __future__ import annotations


class AppSdkError(Exception):
    """Base error for SDK app creation and validation."""


class AppSdkTemplateError(AppSdkError):
    """Raised when a requested SDK template is unknown or invalid."""


class AppSdkPathError(AppSdkError):
    """Raised when an SDK operation would write outside an allowed root."""


class AppSdkValidationError(AppSdkError):
    """Raised when SDK validation fails."""
