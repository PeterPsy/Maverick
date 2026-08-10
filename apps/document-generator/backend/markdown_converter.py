"""Docling-backed Markdown conversion for workspace documents."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Any
from uuid import uuid4

from errors import DocumentValidationError
from store import safe_output_filename, save_job, utc_now
from workspace_files import resolve_workspace_file, workspace_relative_generated_path


SUPPORTED_MARKDOWN_FORMATS = {"pdf", "docx", "pptx", "xlsx"}
# Conversion runs synchronously through the generic app entrypoint timeout.
MAX_MARKDOWN_SOURCE_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_RETURN_CHARS = 20000
MAX_RETURN_CHARS_LIMIT = 200000
MARKDOWN_OUTPUT_ROOT = Path("document-generator") / "markdown"


def convert_workspace_file_to_markdown(
    data_root: Path,
    uploaded_root: Path | None,
    generated_root: Path,
    body: dict[str, Any],
    *,
    local_app_id: str = "document-generator",
) -> dict[str, Any]:
    """Convert one workspace document to Markdown and save it as a generated artifact."""
    workspace_relative_path = str(body.get("workspace_relative_path") or "").strip()
    if not workspace_relative_path:
        raise DocumentValidationError("workspace_relative_path is required.")
    source = resolve_workspace_file(uploaded_root, generated_root, workspace_relative_path)
    source_format = source.suffix.lower().lstrip(".")
    if source_format not in SUPPORTED_MARKDOWN_FORMATS:
        raise DocumentValidationError(f"Unsupported Markdown conversion format `{source_format}`.")
    if source.stat().st_size > MAX_MARKDOWN_SOURCE_FILE_BYTES:
        raise DocumentValidationError("workspace file exceeds the 10 MiB synchronous Markdown conversion limit.")

    markdown = _convert_with_docling(source)
    job_id = uuid4().hex
    title = _normalize_title(body.get("title"), fallback=source.stem)
    filename = safe_output_filename(str(body.get("output_filename") or "").strip() or None, title=title, output_format="md")
    target = _markdown_output_path(generated_root, job_id, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_ensure_trailing_newline(markdown), encoding="utf-8")

    job = {
        "job_id": job_id,
        "title": title,
        "format": "md",
        "filename": target.name,
        "workspace_relative_path": workspace_relative_generated_path(target, generated_root),
        "size_bytes": target.stat().st_size,
        "created_at": utc_now(),
        "metadata": {
            "kind": "markdown_conversion",
            "engine": "docling",
            "engine_version": _docling_version(),
            "request_metadata": _metadata_payload(body.get("metadata")),
            "source_workspace_relative_path": workspace_relative_path,
            "source_filename": source.name,
            "source_format": source_format,
            "source_size_bytes": source.stat().st_size,
        },
    }
    save_job(data_root, job)

    result: dict[str, Any] = {
        "document": job,
        "source": {
            "workspace_relative_path": workspace_relative_path,
            "filename": source.name,
            "format": source_format,
            "size_bytes": source.stat().st_size,
        },
        "markdown_path": job["workspace_relative_path"],
        "manifest_path": f"data/{_safe_local_app_id(local_app_id)}/jobs/{job_id}.json",
        "markdown_length": len(markdown),
    }
    if bool(body.get("return_markdown")):
        max_chars = _normalize_max_return_chars(body.get("max_return_chars"))
        returned = markdown[:max_chars].rstrip()
        result["markdown"] = returned
        result["markdown_truncated"] = len(markdown) > max_chars
    return result


def _convert_with_docling(source: Path) -> str:
    converter_class = _load_docling_converter_class()
    try:
        result = converter_class().convert(source)
        document = getattr(result, "document", None)
        if document is None or not hasattr(document, "export_to_markdown"):
            raise DocumentValidationError("Docling did not return a Markdown-capable document.")
        markdown = document.export_to_markdown()
    except DocumentValidationError:
        raise
    except Exception as error:
        raise DocumentValidationError(f"Docling conversion failed for `{source.name}`: {error}") from None
    if not isinstance(markdown, str):
        raise DocumentValidationError("Docling Markdown export did not return text.")
    return markdown


def _load_docling_converter_class() -> type:
    try:
        from docling.document_converter import DocumentConverter
    except ModuleNotFoundError as error:
        if error.name == "docling":
            raise DocumentValidationError(
                "Docling is not installed. Install the document-generator extra with "
                "`python3 -m pip install -e '.[document-generator]'`. On Linux CPU-only hosts, add "
                "`--extra-index-url https://download.pytorch.org/whl/cpu` to avoid installing CUDA packages."
            ) from None
        missing_name = error.name or "a required package"
        raise DocumentValidationError(
            f"Docling is installed without `{missing_name}`. Reinstall the document-generator extra with "
            "`python3 -m pip install -e '.[document-generator]'`. On Linux CPU-only hosts, add "
            "`--extra-index-url https://download.pytorch.org/whl/cpu` to avoid installing CUDA packages."
        ) from None
    return DocumentConverter


def _docling_version() -> str:
    try:
        return metadata.version("docling")
    except metadata.PackageNotFoundError:
        return "unknown"


def _markdown_output_path(generated_root: Path, job_id: str, filename: str) -> Path:
    root = generated_root.resolve()
    target = (root / MARKDOWN_OUTPUT_ROOT / job_id / filename).resolve()
    if root != target and root not in target.parents:
        raise DocumentValidationError("Markdown output path escapes generated storage.")
    return target


def _normalize_title(raw_title: object, *, fallback: str) -> str:
    title = " ".join(str(raw_title or fallback or "Converted document").split())
    return title or "Converted document"


def _normalize_max_return_chars(raw_value: object) -> int:
    try:
        value = int(raw_value or DEFAULT_MAX_RETURN_CHARS)
    except (TypeError, ValueError):
        raise DocumentValidationError("max_return_chars must be an integer.") from None
    return max(1, min(value, MAX_RETURN_CHARS_LIMIT))


def _metadata_payload(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_local_app_id(value: object) -> str:
    normalized = str(value or "document-generator").strip()
    if not normalized:
        return "document-generator"
    if "/" in normalized or "\\" in normalized or "\x00" in normalized or ".." in Path(normalized).parts:
        raise DocumentValidationError("app_id is invalid.")
    return normalized


def _ensure_trailing_newline(value: str) -> str:
    return value if value.endswith("\n") else f"{value}\n"
