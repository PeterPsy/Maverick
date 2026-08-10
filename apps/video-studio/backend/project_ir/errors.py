"""Stable deterministic errors shared by every Project IR surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, order=True)
class ValidationIssue:
    """One validation failure with a stable code and JSON-pointer path."""

    path: str
    code: str
    message: str
    details: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "details": {key: value for key, value in self.details},
        }


class IRValidationError(ValueError):
    """Raised only after every deterministic validation issue is collected."""

    code = "project_ir_invalid"

    def __init__(self, issues: list[ValidationIssue] | tuple[ValidationIssue, ...]) -> None:
        ordered = tuple(sorted(issues))
        if not ordered:
            raise ValueError("IRValidationError requires at least one issue.")
        self.issues = ordered
        super().__init__(f"Project IR validation failed with {len(ordered)} issue(s).")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "path": "",
            "details": {"issues": [issue.to_dict() for issue in self.issues]},
        }


def issue(
    code: str,
    path: str,
    message: str,
    **details: Any,
) -> ValidationIssue:
    """Build an issue with deterministically ordered detail keys."""

    return ValidationIssue(
        path=path,
        code=code,
        message=message,
        details=tuple(sorted(details.items())),
    )
