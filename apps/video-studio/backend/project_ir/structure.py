"""Strict structural validation sourced from the committed JSON Schema."""

from __future__ import annotations

from .errors import ValidationIssue
from .schema_validation import schema_issues


def structural_issues(document: object) -> list[ValidationIssue]:
    return schema_issues(document)
