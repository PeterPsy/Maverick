"""Compatibility facade for Calendar surface metadata and errors."""

from __future__ import annotations

from surface_actions import ALLOWED_ACTIONS, EXPECTED_FIELDS_BY_ACTION, normalize_action
from surface_errors import (
    conflict_error,
    not_found_error,
    revision_conflict_error,
    unsupported_action,
    validation_error,
)
from surface_manifest import operations_manifest, reference_manifest


__all__ = [
    "ALLOWED_ACTIONS",
    "EXPECTED_FIELDS_BY_ACTION",
    "conflict_error",
    "normalize_action",
    "not_found_error",
    "operations_manifest",
    "reference_manifest",
    "revision_conflict_error",
    "unsupported_action",
    "validation_error",
]
