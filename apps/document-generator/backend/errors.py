"""Errors for the Document Generator app."""

from __future__ import annotations


class DocumentGeneratorError(Exception):
    """Base app error."""


class DocumentValidationError(DocumentGeneratorError):
    """Raised when a document request is invalid."""
