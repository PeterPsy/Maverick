"""Renderer-independent Video Studio Project IR v1."""

from .canonical import canonical_bytes, canonical_dumps, content_digest
from .errors import IRValidationError, ValidationIssue
from .models import ProjectIR, ValidationLimits
from .registry import ProjectRegistry, default_registry
from .temporal import Rational, Rounding
from .validator import validate_project_ir

__all__ = [
    "IRValidationError",
    "ProjectIR",
    "ProjectRegistry",
    "Rational",
    "Rounding",
    "ValidationIssue",
    "ValidationLimits",
    "canonical_bytes",
    "canonical_dumps",
    "content_digest",
    "default_registry",
    "validate_project_ir",
]
