"""Workspace document text extraction service."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from errors import DocumentValidationError
from office_extractors import extract_docx_text, extract_pptx_text, extract_xlsx_text
from pdf_extractor import extract_pdf_text
from workspace_files import resolve_workspace_file


SUPPORTED_EXTRACT_FORMATS = {"pdf", "docx", "pptx", "xlsx"}
DEFAULT_MAX_CHARS = 50000
MAX_CHARS_LIMIT = 200000
MAX_EXTRACT_FILE_BYTES = 25 * 1024 * 1024


def extract_text_from_workspace_file(uploaded_root: Path | None, generated_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    workspace_relative_path = str(body.get("workspace_relative_path") or "").strip()
    if not workspace_relative_path:
        raise DocumentValidationError("workspace_relative_path is required.")
    target = resolve_workspace_file(uploaded_root, generated_root, workspace_relative_path)
    file_format = _format_from_path(target)
    if file_format not in SUPPORTED_EXTRACT_FORMATS:
        raise DocumentValidationError(f"Unsupported extraction format `{file_format}`.")
    if target.stat().st_size > MAX_EXTRACT_FILE_BYTES:
        raise DocumentValidationError("workspace file is too large for text extraction.")

    max_chars = _normalize_max_chars(body.get("max_chars"))
    text = _extract_by_format(target, file_format)
    normalized = _normalize_text(text)
    truncated = len(normalized) > max_chars
    if truncated:
        normalized = normalized[:max_chars].rstrip()

    return {
        "document": {
            "workspace_relative_path": workspace_relative_path,
            "filename": target.name,
            "format": file_format,
            "size_bytes": target.stat().st_size,
        },
        "text": normalized,
        "text_length": len(normalized),
        "truncated": truncated,
    }


def _normalize_max_chars(raw_value: object) -> int:
    try:
        value = int(raw_value or DEFAULT_MAX_CHARS)
    except (TypeError, ValueError):
        raise DocumentValidationError("max_chars must be an integer.") from None
    return max(1, min(value, MAX_CHARS_LIMIT))


def _format_from_path(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _extract_by_format(path: Path, file_format: str) -> str:
    if file_format == "docx":
        return extract_docx_text(path)
    if file_format == "pptx":
        return extract_pptx_text(path)
    if file_format == "xlsx":
        return extract_xlsx_text(path)
    if file_format == "pdf":
        return extract_pdf_text(path)
    raise DocumentValidationError(f"Unsupported extraction format `{file_format}`.")


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line
        if blank and previous_blank:
            continue
        normalized.append(line)
        previous_blank = blank
    return "\n".join(normalized).strip()
