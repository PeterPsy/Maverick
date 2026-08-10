"""Stable domain errors for projects, revisions, and operation batches."""

from __future__ import annotations

from typing import Any


class ProjectError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str = "",
        details: dict[str, Any] | None = None,
        status_code: int = 400,
    ) -> None:
        self.code = code
        self.path = path
        self.details = {key: value for key, value in sorted((details or {}).items())}
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": str(self),
            "details": self.details,
        }


def not_found(kind: str, identifier: str) -> ProjectError:
    return ProjectError(
        f"{kind}_not_found",
        f"{kind.replace('_', ' ').capitalize()} was not found.",
        details={f"{kind}_id": identifier},
        status_code=404,
    )


def stale_revision(expected: str, actual: str) -> ProjectError:
    return ProjectError(
        "stale_revision_conflict",
        "Project head no longer matches the requested base revision.",
        path="/base_revision_id",
        details={"actual_revision_id": actual, "expected_revision_id": expected},
        status_code=409,
    )


def concurrency_conflict() -> ProjectError:
    return ProjectError(
        "concurrent_head_update",
        "Project head changed during the transaction.",
        status_code=409,
    )
