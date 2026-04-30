"""Workspace storage inventory helpers for the Gallery app."""

from __future__ import annotations

from base64 import b64decode
import binascii
from pathlib import Path
import re
import shutil

from core.app_sdk.storage import read_json_state, write_json_state
from errors import GalleryValidationError
from text_preview import MAX_TABLE_PREVIEW_COLUMNS, MAX_TABLE_PREVIEW_ROWS, MAX_TEXT_PREVIEW_CHARS, extract_table_preview, extract_text_preview


SCHEMA_VERSION = "1"
MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_READ_BYTES = 100 * 1024 * 1024
FILE_ROLES = {"uploaded", "generated"}
UPLOAD_BUCKET_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
VIEW_FILTER_ROLES = {"all", *FILE_ROLES}
VIEW_FILTER_KINDS = {"all", "image", "video", "audio", "markdown", "text", "pdf", "document", "presentation", "spreadsheet", "file"}
MAX_VIEW_QUERY_CHARS = 200
MAX_CUSTOM_VIEW_TITLE_CHARS = 140
MAX_CUSTOM_VIEW_FILES = 500
MAX_TEXT_PREVIEW_CACHE_ENTRIES = 200
MAX_MARKDOWN_EDIT_BYTES = 2 * 1024 * 1024
MAX_WRITE_BYTES = 25 * 1024 * 1024


def upload_file_payload(
    *,
    role: str,
    folder_relative_path: object,
    file_name: object,
    content_base64: object,
    uploaded_root: Path,
    generated_root: Path,
) -> dict:
    payload = _write_content_bytes(content=None, content_base64=content_base64)
    folder = resolve_storage_folder(
        role=role,
        relative_path=folder_relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    target = (folder / safe_file_name(str(file_name or ""))).resolve()
    if root not in target.parents:
        raise GalleryValidationError("Uploaded file must stay inside the selected storage root.")
    if target.exists():
        raise GalleryValidationError("A file or folder with that name already exists in the target folder.")
    target.write_bytes(payload)
    return {"file": file_record(role=role, root=root, path=target), "bytes_written": len(payload)}



def _write_content_bytes(*, content: object, content_base64: object) -> bytes:
    if content_base64 is not None:
        try:
            payload = b64decode(str(content_base64), validate=True)
        except (ValueError, binascii.Error) as error:
            raise GalleryValidationError("content_base64 must be valid base64.") from error
    elif isinstance(content, str):
        payload = content.encode("utf-8")
    else:
        raise GalleryValidationError("content or content_base64 is required.")
    if len(payload) > MAX_WRITE_BYTES:
        raise GalleryValidationError(f"Written file content must be at most {MAX_WRITE_BYTES} bytes.")
    return payload



def preview_text_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path, data_root: Path, max_chars: int | None) -> dict:
    if max_chars is not None and (max_chars <= 0 or max_chars > MAX_TEXT_PREVIEW_CHARS):
        raise GalleryValidationError(f"max_chars must be between 1 and {MAX_TEXT_PREVIEW_CHARS}.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = file_record(role=role, root=root, path=path.resolve())
    cache_key = _text_preview_cache_key(record, max_chars)
    cache = _load_text_preview_cache(data_root)
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        return {"file": record, "preview_text": cached, "cache_hit": True}
    preview_text = extract_text_preview(path, record["preview_kind"], max_chars)
    if max_chars is not None or len(preview_text) <= MAX_TEXT_PREVIEW_CHARS:
        cache[cache_key] = preview_text
        _write_text_preview_cache(data_root, cache)
    return {"file": record, "preview_text": preview_text, "cache_hit": False}



def preview_table_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path, max_rows: int | None, max_columns: int | None) -> dict:
    if max_rows is not None and (max_rows <= 0 or max_rows > MAX_TABLE_PREVIEW_ROWS):
        raise GalleryValidationError(f"max_rows must be between 1 and {MAX_TABLE_PREVIEW_ROWS}.")
    if max_columns is not None and (max_columns <= 0 or max_columns > MAX_TABLE_PREVIEW_COLUMNS):
        raise GalleryValidationError(f"max_columns must be between 1 and {MAX_TABLE_PREVIEW_COLUMNS}.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = file_record(role=role, root=root, path=path.resolve())
    if record["preview_kind"] != "spreadsheet" and record["extension"].lower() != ".csv":
        raise GalleryValidationError("Table preview is only available for CSV and spreadsheet files.")
    table = extract_table_preview(path, record["preview_kind"], max_rows=max_rows, max_columns=max_columns)
    return {"file": record, "sheets": table["sheets"]}



def file_info_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path) -> dict:
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    return {"file": file_record(role=role, root=root, path=path.resolve())}



def update_markdown_file_payload(*, role: str, relative_path: str, content: object, uploaded_root: Path, generated_root: Path) -> dict:
    if not isinstance(content, str):
        raise GalleryValidationError("content must be a string.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_MARKDOWN_EDIT_BYTES:
        raise GalleryValidationError(f"Markdown content must be at most {MAX_MARKDOWN_EDIT_BYTES} bytes.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = file_record(role=role, root=root, path=path.resolve())
    if record["preview_kind"] != "markdown":
        raise GalleryValidationError("Only Markdown files can be edited in the Gallery Markdown editor.")
    path.write_text(content, encoding="utf-8")
    return {"file": file_record(role=role, root=root, path=path.resolve())}



def create_folder_payload(*, role: str, parent_relative_path: object, folder_name: object, uploaded_root: Path, generated_root: Path) -> dict:
    parent = resolve_storage_folder(
        role=role,
        relative_path=parent_relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    target = (parent / safe_folder_name(folder_name)).resolve()
    if root not in target.parents:
        raise GalleryValidationError("Folder must stay inside the selected storage root.")
    if target.exists():
        raise GalleryValidationError("A folder or file with that name already exists.")
    target.mkdir()
    return {"folder": folder_record(role=role, root=root, path=target)}



def move_file_payload(*, role: str, relative_path: str, target_folder_relative_path: object, uploaded_root: Path, generated_root: Path) -> dict:
    source = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    target_folder = resolve_storage_folder(
        role=role,
        relative_path=target_folder_relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    target = (target_folder / source.name).resolve()
    if root not in target.parents:
        raise GalleryValidationError("Moved file must stay inside the selected storage root.")
    if target.exists() and target != source:
        raise GalleryValidationError("A file or folder with that name already exists in the target folder.")
    if target == source:
        return {"file": file_record(role=role, root=root, path=source)}
    shutil.move(str(source), str(target))
    return {"file": file_record(role=role, root=root, path=target)}



def _load_text_preview_cache(data_root: Path) -> dict:
    path = text_preview_cache_path(data_root)
    if not path.exists():
        return {}
    payload = read_json_state(data_root, "preview_cache.json", {})
    return payload if isinstance(payload, dict) else {}



def _write_text_preview_cache(data_root: Path, cache: dict) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    entries = list(cache.items())[-MAX_TEXT_PREVIEW_CACHE_ENTRIES:]
    write_json_state(data_root, "preview_cache.json", dict(entries))



def _text_preview_cache_key(record: dict, max_chars: int | None) -> str:
    return "|".join(
        [
            record["id"],
            record["modified_at"],
            str(record["size_bytes"]),
            record["preview_kind"],
            "full" if max_chars is None else str(max_chars),
        ]
    )



def rename_file_payload(*, role: str, relative_path: str, new_name: str, uploaded_root: Path, generated_root: Path) -> dict:
    source = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    normalized_name = safe_file_name(new_name)
    target = source.with_name(normalized_name).resolve()
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    if root not in target.parents:
        raise GalleryValidationError("Renamed file must stay inside the selected storage root.")
    if target.exists() and target != source:
        raise GalleryValidationError("A file with that name already exists.")
    if target == source:
        return {"file": file_record(role=role, root=root, path=source)}
    source.rename(target)
    return {"file": file_record(role=role, root=root, path=target)}
