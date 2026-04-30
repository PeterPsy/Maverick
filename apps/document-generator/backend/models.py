"""Document specification normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from errors import DocumentValidationError


SUPPORTED_FORMATS = {"docx", "pptx", "pdf", "xlsx"}


@dataclass(frozen=True)
class DocumentSpec:
    """Normalized document generation request."""

    title: str
    format: str
    output_filename: str | None
    sections: list[dict[str, Any]]
    slides: list[dict[str, Any]]
    sheets: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    metadata: dict[str, Any]


def _object_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DocumentValidationError(f"{field_name} must be a list.")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            normalized.append({"text": item})
        elif isinstance(item, dict):
            normalized.append(dict(item))
        else:
            raise DocumentValidationError(f"{field_name}[{index}] must be an object or string.")
    return normalized


def normalize_spec(raw: Any) -> DocumentSpec:
    """Validate and normalize a document spec payload."""
    if not isinstance(raw, dict):
        raise DocumentValidationError("spec must be a JSON object.")
    output_format = str(raw.get("format") or "").strip().lower()
    if output_format not in SUPPORTED_FORMATS:
        raise DocumentValidationError("format must be one of: docx, pdf, pptx, xlsx.")
    title = " ".join(str(raw.get("title") or "Untitled document").split())
    if not title:
        raise DocumentValidationError("title is required.")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return DocumentSpec(
        title=title,
        format=output_format,
        output_filename=str(raw.get("output_filename") or "").strip() or None,
        sections=_object_list(raw.get("sections"), "sections"),
        slides=_object_list(raw.get("slides"), "slides"),
        sheets=_object_list(raw.get("sheets"), "sheets"),
        tables=_object_list(raw.get("tables"), "tables"),
        metadata=dict(metadata),
    )
