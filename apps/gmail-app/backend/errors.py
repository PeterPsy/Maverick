"""Gmail App domain errors."""

from __future__ import annotations


class GmailAppError(Exception):
    """Base error for expected Gmail App failures."""


class GmailAppValidationError(GmailAppError):
    """Raised when an app action receives invalid input."""


class GmailApprovalError(GmailAppValidationError):
    """Raised when a send request is not explicitly approved."""


class GmailConnectionError(GmailAppError):
    """Raised when Gmail cannot be called with the available credentials."""
