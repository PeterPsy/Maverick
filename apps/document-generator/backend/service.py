"""Document Generator app service layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from errors import DocumentValidationError
from extractors import extract_text_from_workspace_file
from generators.docx_generator import generate_docx
from generators.pdf_generator import generate_pdf
from generators.pptx_generator import generate_pptx
from generators.xlsx_generator import generate_xlsx
from markdown_converter import convert_workspace_file_to_markdown
from models import normalize_spec
from pdf_editor import modify_uploaded_document, patch_pdf_text
from spreadsheet_transform import transform_spreadsheet
from store import (
    list_jobs,
    list_templates,
    resolve_generated_path,
    safe_output_filename,
    save_job,
    seed_state,
    clear_custom_view_payload,
    set_custom_view_payload,
    set_view_filter_payload,
    utc_now,
    view_state,
)


REFERENCE_MANIFEST = {
    "app_id": "document-generator",
    "schema_version": "1",
    "entity_types": [
        {
            "entity_type": "document",
            "display_name": "Generated Document",
            "id_stability": "stable",
            "searchable": True,
            "resolvable": True,
            "summarizable": True,
            "deep_link_supported": True,
        }
    ],
}


def app_events_for_action(action: str) -> list[dict]:
    if action in {"generate_document", "convert_to_markdown", "patch_pdf_text", "modify_uploaded_document", "spreadsheet.transform"}:
        return [{"type": "maverick.app.data-changed", "resource": "documents"}]
    if action in {"set_view_filter", "set_custom_view", "clear_custom_view"}:
        return [{"type": "maverick.app.data-changed", "resource": "view-state"}]
    return []


def app_events_for_result(action: str, result: dict[str, Any]) -> list[dict]:
    if action in {"patch_pdf_text", "modify_uploaded_document"} and result.get("status") != "patched":
        return []
    return app_events_for_action(action)


def _pymupdf_health() -> dict[str, Any]:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception as error:
        return {
            "available": False,
            "required": True,
            "package": "PyMuPDF",
            "module": "fitz",
            "detail": str(error),
        }
    return {
        "available": True,
        "required": True,
        "package": "PyMuPDF",
        "module": "fitz",
        "version": str(getattr(fitz, "__version__", "") or ""),
    }


def _workspace_relative(path: Path, generated_root: Path) -> str:
    return f"storage/generated/{path.relative_to(generated_root).as_posix()}"


def _document_reference(record: dict[str, Any]) -> dict[str, Any]:
    summary = f"{str(record.get('format') or '').upper()} generated document"
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if metadata.get("kind") == "markdown_conversion":
        source_format = str(metadata.get("source_format") or "document").upper()
        summary = f"Markdown converted from {source_format}"
    return {
        "app_id": "document-generator",
        "entity_type": "document",
        "entity_id": str(record["job_id"]),
        "title": str(record.get("title") or record.get("filename") or "Generated document"),
        "subtitle": str(record.get("workspace_relative_path") or ""),
        "summary": summary,
        "confidence": 1.0,
        "deep_link": f"/apps/storage?path={record.get('workspace_relative_path')}",
        "workspace_relative_path": record.get("workspace_relative_path"),
    }


def generate_document(data_root: Path, generated_root: Path, raw_spec: Any) -> dict[str, Any]:
    spec = normalize_spec(raw_spec)
    filename = safe_output_filename(spec.output_filename, title=spec.title, output_format=spec.format)
    target = resolve_generated_path(generated_root, filename)
    if spec.format == "docx":
        generate_docx(spec, target)
    elif spec.format == "pptx":
        generate_pptx(spec, target)
    elif spec.format == "pdf":
        generate_pdf(spec, target)
    elif spec.format == "xlsx":
        generate_xlsx(spec, target)
    else:
        raise DocumentValidationError(f"Unsupported format `{spec.format}`.")

    job = {
        "job_id": uuid4().hex,
        "title": spec.title,
        "format": spec.format,
        "filename": target.name,
        "workspace_relative_path": _workspace_relative(target, generated_root.resolve()),
        "size_bytes": target.stat().st_size,
        "created_at": utc_now(),
        "metadata": spec.metadata,
    }
    save_job(data_root, job)
    return {"document": job}


def validate_spec(raw_spec: Any) -> dict[str, Any]:
    spec = normalize_spec(raw_spec)
    return {
        "valid": True,
        "format": spec.format,
        "title": spec.title,
        "sections": len(spec.sections),
        "slides": len(spec.slides),
        "sheets": len(spec.sheets),
        "tables": len(spec.tables),
    }


def handle_action(
    data_root: Path,
    generated_root: Path,
    body: dict[str, Any],
    uploaded_root: Path | None = None,
    *,
    local_app_id: str = "document-generator",
) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "generate_document")
    if action == "generate_document":
        return 200, generate_document(data_root, generated_root, body.get("spec"))
    if action == "validate_spec":
        return 200, validate_spec(body.get("spec"))
    if action == "extract_text":
        return 200, extract_text_from_workspace_file(uploaded_root, generated_root, body)
    if action == "patch_pdf_text":
        return 200, patch_pdf_text(data_root, uploaded_root, generated_root, body, local_app_id=local_app_id)
    if action == "modify_uploaded_document":
        return 200, modify_uploaded_document(data_root, uploaded_root, generated_root, body, local_app_id=local_app_id)
    if action == "convert_to_markdown":
        return 200, convert_workspace_file_to_markdown(data_root, uploaded_root, generated_root, body, local_app_id=local_app_id)
    if action == "spreadsheet.transform":
        return 200, transform_spreadsheet(data_root, uploaded_root, generated_root, body)
    if action == "list_templates":
        return 200, {"templates": list_templates(data_root)}
    if action == "list_outputs":
        return 200, {"documents": list_jobs(data_root)}
    if action == "view_filter":
        return 200, {"state": view_state(data_root)}
    if action == "set_view_filter":
        return 200, {"state": set_view_filter_payload(data_root, body)}
    if action == "set_custom_view":
        return 200, {"state": set_custom_view_payload(data_root, body)}
    if action == "clear_custom_view":
        return 200, {"state": clear_custom_view_payload(data_root)}
    if action == "health.check":
        seed_state(data_root)
        generated_root.mkdir(parents=True, exist_ok=True)
        pymupdf = _pymupdf_health()
        healthy = bool(pymupdf.get("available"))
        result = {
            "status": "ok" if healthy else "degraded",
            "templates": len(list_templates(data_root)),
            "documents": len(list_jobs(data_root)),
            "dependencies": {
                "pymupdf": pymupdf,
            },
        }
        if not healthy:
            result["detail"] = "PyMuPDF is required for PDF text patching but is not available in the runtime."
        return 200, result
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        query = str(body.get("query") or "").casefold()
        limit = max(1, min(int(body.get("limit") or 10), 50))
        refs = [_document_reference(record) for record in list_jobs(data_root)]
        if query:
            refs = [item for item in refs if query in item["title"].casefold() or query in item["subtitle"].casefold()]
        return 200, {"results": refs[:limit]}
    if action == "references.resolve":
        entity_id = str(body.get("entity_id") or "").strip()
        item = next((_document_reference(record) for record in list_jobs(data_root) if str(record.get("job_id")) == entity_id), None)
        return 200, {"exists": False, "app_id": "document-generator", "entity_type": "document", "entity_id": entity_id} if item is None else {"exists": True, **item}
    if action == "references.summarize":
        _status, resolved = handle_action(data_root, generated_root, {"action": "references.resolve", "entity_id": str(body.get("entity_id") or "")})
        if not resolved.get("exists"):
            return 200, {"summary": "", "safe_fields": {}, "source_updated_at": ""}
        return 200, {
            "summary": resolved.get("summary") or resolved.get("title") or "",
            "safe_fields": {"title": resolved.get("title"), "path": resolved.get("workspace_relative_path")},
            "source_updated_at": "",
        }
    raise DocumentValidationError(f"Unknown action `{action}`.")
