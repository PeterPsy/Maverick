"""PDF text patching workflow for Document Generator."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from errors import DocumentValidationError
from pdf_extractor import extract_pdf_text_details
from store import safe_output_filename, save_job, utc_now
from workspace_files import resolve_workspace_file, workspace_relative_generated_path


MAX_PATCHES = 20
MAX_REPLACEMENT_CHARS = 500
DATE_PATTERN = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
SAFE_LOCAL_APP_ID_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class PdfTextPatch:
    match_text: str
    replacement_text: str
    occurrence: int | str
    redact_original: bool
    case_sensitive: bool
    page_number: int | None


@dataclass(frozen=True)
class PdfPatchEdit:
    patch_index: int
    page_index: int
    rect: Any
    replacement_text: str
    redact_original: bool


def patch_pdf_text(
    data_root: Path,
    uploaded_root: Path | None,
    generated_root: Path,
    body: dict[str, Any],
    *,
    local_app_id: str = "document-generator",
) -> dict[str, Any]:
    """Patch matched text in one workspace PDF and save a generated artifact."""
    source_path = _resolve_pdf_source(uploaded_root, generated_root, body)
    patches = _normalize_patches(body.get("patches"))
    job_id = uuid4().hex
    output_dir = generated_root.resolve() / _safe_local_app_id(local_app_id) / "pdf-edits" / job_id
    filename = safe_output_filename(
        str(body.get("output_filename") or f"{source_path.stem}-patched.pdf"),
        title=f"{source_path.stem}-patched",
        output_format="pdf",
    )
    target = (output_dir / filename).resolve()
    if generated_root.resolve() not in target.parents:
        raise DocumentValidationError("PDF edit output path escapes generated storage.")
    target.parent.mkdir(parents=True, exist_ok=True)

    fitz = _load_pymupdf()
    patch_results: list[dict[str, Any]] = []
    edits: list[PdfPatchEdit] = []
    with fitz.open(source_path) as document:
        for index, patch in enumerate(patches):
            matches = _find_patch_matches(document, patch)
            selected = _select_patch_matches(matches, patch)
            patch_results.append(
                {
                    "patch_index": index,
                    "match_text": patch.match_text,
                    "replacement_text": patch.replacement_text,
                    "old_match_count": len(matches),
                    "replacements_applied": len(selected),
                    "page_numbers": sorted({page_index + 1 for page_index, _rect in selected}),
                }
            )
            for page_index, rect in selected:
                edits.append(
                    PdfPatchEdit(
                        patch_index=index,
                        page_index=page_index,
                        rect=fitz.Rect(rect),
                        replacement_text=patch.replacement_text,
                        redact_original=patch.redact_original,
                    )
                )
        _apply_edits(document, edits, fitz)
        document.save(target, garbage=4, deflate=True)

    output_text_details = extract_pdf_text_details(target)
    output_text = str(output_text_details.get("text") or "")
    for patch, result in zip(patches, patch_results, strict=True):
        result["remaining_old_match_count"] = _count_text(
            output_text,
            patch.match_text,
            case_sensitive=patch.case_sensitive,
        )
        result["new_match_count"] = (
            _count_text(output_text, patch.replacement_text, case_sensitive=patch.case_sensitive)
            if patch.replacement_text
            else 0
        )

    visual_artifact = _write_visual_verification_artifact(
        target=target,
        output_dir=output_dir,
        edit=edits[0] if edits else None,
        fitz=fitz,
    )
    workspace_relative_path = workspace_relative_generated_path(target, generated_root)
    visual_workspace_path = (
        workspace_relative_generated_path(visual_artifact, generated_root)
        if visual_artifact is not None
        else ""
    )
    job = {
        "job_id": job_id,
        "title": str(body.get("title") or f"PDF edit: {source_path.name}"),
        "format": "pdf",
        "filename": target.name,
        "workspace_relative_path": workspace_relative_path,
        "size_bytes": target.stat().st_size,
        "created_at": utc_now(),
        "metadata": {
            "kind": "pdf_text_patch",
            "source_workspace_relative_path": str(body.get("workspace_relative_path") or ""),
            "patches": patch_results,
            "extraction": {
                "engine": output_text_details.get("engine"),
                "layers": output_text_details.get("layers"),
            },
            "visual_diff_artifact": visual_workspace_path,
        },
    }
    save_job(data_root, job)
    return {
        "status": "patched",
        "document": job,
        "workspace_relative_path": workspace_relative_path,
        "sha256": _hash_file(target),
        "patches": patch_results,
        "old_match_count": sum(int(item["old_match_count"]) for item in patch_results),
        "new_match_count": sum(int(item["new_match_count"]) for item in patch_results),
        "visual_diff_artifact": visual_workspace_path,
    }


def modify_uploaded_document(
    data_root: Path,
    uploaded_root: Path | None,
    generated_root: Path,
    body: dict[str, Any],
    *,
    local_app_id: str = "document-generator",
) -> dict[str, Any]:
    """Task-level document edit helper for common uploaded PDF text replacements."""
    if body.get("patches"):
        return patch_pdf_text(data_root, uploaded_root, generated_root, body, local_app_id=local_app_id)

    replacement_text = str(body.get("replacement_text") or "").strip()
    if not replacement_text:
        raise DocumentValidationError("replacement_text is required.")
    match_text = str(body.get("match_text") or body.get("confirmed_match_text") or "").strip()
    if not match_text:
        source_path = _resolve_pdf_source(uploaded_root, generated_root, body)
        candidates = _date_candidates(str(extract_pdf_text_details(source_path).get("text") or ""))
        if not candidates:
            raise DocumentValidationError("No date candidates were found in the PDF.")
        if len(candidates) > 1:
            return {
                "status": "needs_confirmation",
                "reason": "multiple_date_candidates",
                "candidates": candidates,
                "required_fields": ["match_text"],
            }
        match_text = candidates[0]["text"]

    patch_body = {
        **body,
        "patches": [
            {
                "match_text": match_text,
                "replacement_text": replacement_text,
                "occurrence": int(body.get("occurrence") or 1),
                "redact_original": body.get("redact_original", True),
            }
        ],
    }
    return patch_pdf_text(data_root, uploaded_root, generated_root, patch_body, local_app_id=local_app_id)


def _resolve_pdf_source(uploaded_root: Path | None, generated_root: Path, body: dict[str, Any]) -> Path:
    workspace_relative_path = str(body.get("workspace_relative_path") or "").strip()
    if not workspace_relative_path:
        raise DocumentValidationError("workspace_relative_path is required.")
    source = resolve_workspace_file(uploaded_root, generated_root, workspace_relative_path)
    if source.suffix.lower() != ".pdf":
        raise DocumentValidationError("PDF text patching requires a .pdf workspace file.")
    return source


def _normalize_patches(raw_patches: object) -> list[PdfTextPatch]:
    if not isinstance(raw_patches, list) or not raw_patches:
        raise DocumentValidationError("patches must be a non-empty array.")
    if len(raw_patches) > MAX_PATCHES:
        raise DocumentValidationError(f"patches must contain at most {MAX_PATCHES} items.")
    patches: list[PdfTextPatch] = []
    for raw_patch in raw_patches:
        if not isinstance(raw_patch, dict):
            raise DocumentValidationError("Each PDF patch must be an object.")
        match_text = str(raw_patch.get("match_text") or "").strip()
        if not match_text:
            raise DocumentValidationError("Each PDF patch requires match_text.")
        replacement_text = str(raw_patch.get("replacement_text") or "")
        if len(replacement_text) > MAX_REPLACEMENT_CHARS:
            raise DocumentValidationError(f"replacement_text must be at most {MAX_REPLACEMENT_CHARS} characters.")
        occurrence = _normalize_occurrence(raw_patch.get("occurrence", 1))
        page_number = _optional_positive_int(raw_patch.get("page_number"))
        patches.append(
            PdfTextPatch(
                match_text=match_text,
                replacement_text=replacement_text,
                occurrence=occurrence,
                redact_original=_bool_value(raw_patch.get("redact_original", True)),
                case_sensitive=_bool_value(raw_patch.get("case_sensitive", True)),
                page_number=page_number,
            )
        )
    return patches


def _normalize_occurrence(value: object) -> int | str:
    if str(value).strip().lower() == "all":
        return "all"
    try:
        occurrence = int(value or 1)
    except (TypeError, ValueError):
        raise DocumentValidationError("occurrence must be a positive integer or `all`.") from None
    if occurrence <= 0:
        raise DocumentValidationError("occurrence must be a positive integer or `all`.")
    return occurrence


def _optional_positive_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise DocumentValidationError("page_number must be a positive integer.") from None
    if parsed <= 0:
        raise DocumentValidationError("page_number must be a positive integer.")
    return parsed


def _find_patch_matches(document: Any, patch: PdfTextPatch) -> list[tuple[int, Any]]:
    page_indexes = [patch.page_number - 1] if patch.page_number is not None else range(document.page_count)
    matches: list[tuple[int, Any]] = []
    for page_index in page_indexes:
        if page_index < 0 or page_index >= document.page_count:
            raise DocumentValidationError("page_number is outside the PDF page range.")
        page = document[page_index]
        for rect in page.search_for(patch.match_text):
            if not patch.case_sensitive or _rect_contains_text(page, rect, patch.match_text):
                matches.append((page_index, rect))
    return matches


def _rect_contains_text(page: Any, rect: Any, needle: str) -> bool:
    try:
        text = str(page.get_textbox(rect) or "")
    except Exception:
        return False
    if needle in text:
        return True
    return " ".join(needle.split()) in " ".join(text.split())


def _select_patch_matches(matches: list[tuple[int, Any]], patch: PdfTextPatch) -> list[tuple[int, Any]]:
    if not matches:
        raise DocumentValidationError(f"Could not find match_text `{patch.match_text}` in the PDF.")
    if patch.occurrence == "all":
        return matches
    occurrence = int(patch.occurrence)
    if occurrence > len(matches):
        raise DocumentValidationError(f"Could not find occurrence {occurrence} of `{patch.match_text}` in the PDF.")
    return [matches[occurrence - 1]]


def _apply_edits(document: Any, edits: list[PdfPatchEdit], fitz: Any) -> None:
    edits_by_page: dict[int, list[PdfPatchEdit]] = {}
    for edit in edits:
        edits_by_page.setdefault(edit.page_index, []).append(edit)
    for page_index, page_edits in edits_by_page.items():
        page = document[page_index]
        if any(edit.redact_original for edit in page_edits):
            for edit in page_edits:
                if edit.redact_original:
                    page.add_redact_annot(edit.rect, fill=(1, 1, 1))
            page.apply_redactions()
        for edit in page_edits:
            _insert_replacement(page, edit, fitz)


def _insert_replacement(page: Any, edit: PdfPatchEdit, fitz: Any) -> None:
    rect = _expanded_text_rect(page, edit.rect, edit.replacement_text, fitz)
    fontsize = _fit_font_size(edit.replacement_text, rect, fitz)
    spare_height = page.insert_textbox(
        rect,
        edit.replacement_text,
        fontsize=fontsize,
        fontname="helv",
        color=(0, 0, 0),
        align=0,
    )
    if spare_height < 0:
        baseline = min(page.rect.y1 - 1, max(page.rect.y0 + fontsize, edit.rect.y1 - 1))
        page.insert_text((edit.rect.x0, baseline), edit.replacement_text, fontsize=max(5, fontsize - 1), fontname="helv", color=(0, 0, 0))


def _expanded_text_rect(page: Any, rect: Any, text: str, fitz: Any) -> Any:
    width_factor = max(1.0, min(3.0, (len(text) / max(1, rect.width / 5)) * 1.1))
    width = max(rect.width + 4, rect.width * width_factor)
    return fitz.Rect(
        rect.x0,
        max(page.rect.y0, rect.y0 - 1),
        min(page.rect.x1, rect.x0 + width),
        min(page.rect.y1, rect.y1 + 2),
    )


def _fit_font_size(text: str, rect: Any, fitz: Any) -> float:
    height_size = max(5.0, min(14.0, rect.height * 0.72))
    size = height_size
    while size > 5:
        try:
            if fitz.get_text_length(text, fontname="helv", fontsize=size) <= rect.width:
                return size
        except Exception:
            return size
        size -= 0.5
    return 5.0


def _write_visual_verification_artifact(*, target: Path, output_dir: Path, edit: PdfPatchEdit | None, fitz: Any) -> Path | None:
    if edit is None:
        return None
    artifact = output_dir / f"{target.stem}-verification.png"
    try:
        with fitz.open(target) as document:
            page = document[edit.page_index]
            clip = fitz.Rect(
                max(page.rect.x0, edit.rect.x0 - 24),
                max(page.rect.y0, edit.rect.y0 - 18),
                min(page.rect.x1, edit.rect.x1 + 120),
                min(page.rect.y1, edit.rect.y1 + 24),
            )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
            pixmap.save(artifact)
    except Exception:
        return None
    return artifact if artifact.is_file() else None


def _date_candidates(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in DATE_PATTERN.finditer(text):
        value = match.group(0)
        if value in seen:
            continue
        seen.add(value)
        candidates.append({"text": value, "start": match.start(), "end": match.end()})
    return candidates


def _count_text(text: str, needle: str, *, case_sensitive: bool) -> int:
    if not needle:
        return 0
    haystack = text if case_sensitive else text.casefold()
    value = needle if case_sensitive else needle.casefold()
    return haystack.count(value)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_pymupdf():
    try:
        import fitz  # type: ignore[import-not-found]
    except ModuleNotFoundError as error:
        raise DocumentValidationError(
            "PyMuPDF is not installed. Install Maverick runtime dependencies with `python3 -m pip install -e .`."
        ) from error
    return fitz


def _safe_local_app_id(value: str) -> str:
    normalized = SAFE_LOCAL_APP_ID_PATTERN.sub("-", str(value or "document-generator").strip()).strip(".-_")
    return normalized or "document-generator"


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
