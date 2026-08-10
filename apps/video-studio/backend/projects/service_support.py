"""Shared deterministic helpers for the project service."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Callable
from uuid import uuid4

from project_ir import IRValidationError, ProjectIR
from project_ir.canonical import CanonicalizationError, canonical_copy, content_digest

from .errors import ProjectError


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
Clock = Callable[[], str]
IdFactory = Callable[[], str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def random_id() -> str:
    return uuid4().hex


def identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ProjectError("identifier_invalid", "Identifier is missing or malformed.", path=f"/{field}")
    return value


def project_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
        raise ProjectError("project_name_invalid", "Project name must be between 1 and 256 characters.")
    return value.strip()


def validated_document(
    value: object,
    *,
    workspace_id: str,
    project_id: str | None = None,
    name: str | None = None,
) -> ProjectIR:
    try:
        document = canonical_copy(value)
        if project_id is not None:
            document["metadata"]["project_id"] = project_id
        if name is not None:
            document["metadata"]["name"] = name
        return ProjectIR.parse(document, workspace_id=workspace_id)
    except (CanonicalizationError, IRValidationError, KeyError, TypeError) as error:
        details = {}
        if isinstance(error, IRValidationError):
            details = {"issues": [item.to_dict() for item in error.issues]}
        raise ProjectError("project_ir_invalid", "Project IR validation failed.", details=details) from error


def revision_identity(document: dict[str, Any]) -> tuple[str, str]:
    digest = content_digest(document)
    return f"revision-{digest}", digest


def event_payload(project_id: str, revision_id: str | None, change: str) -> dict[str, Any]:
    return {
        "change": change,
        "project_id": project_id,
        "revision_id": revision_id,
    }
