"""Workspace storage record actions for the Storage app."""

from __future__ import annotations

from base64 import b64encode
from io import BytesIO
from pathlib import Path
import re
import shutil
import zipfile

from core.app_sdk.storage import read_json_state, write_json_state
from errors import StorageValidationError
from inventory import content_hash, remove_folder_records, rename_file_record, upsert_directory_record, upsert_file_record
from store_files_paths import (
    atomic_write_bytes,
    enforce_storage_budget,
    folder_record,
    is_system_upload_folder,
    resolve_storage_file,
    resolve_storage_folder,
    safe_file_name,
    safe_folder_name,
    storage_write_lock,
    storage_root_for_role,
    write_content_bytes,
)
from store_files_view import text_preview_cache_path
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
MAX_FOLDER_DOWNLOAD_BYTES = MAX_READ_BYTES


def upload_file_payload(
    *,
    role: str,
    folder_relative_path: object,
    file_name: object,
    content_base64: object,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
) -> dict:
    payload = write_content_bytes(content=None, content_base64=content_base64)
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        folder = resolve_storage_folder(
            role=role,
            relative_path=folder_relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        target = (folder / safe_file_name(str(file_name or ""))).resolve()
        if root not in target.parents:
            raise StorageValidationError("Uploaded file must stay inside the selected storage root.")
        if target.exists():
            raise StorageValidationError("A file or folder with that name already exists in the target folder.")
        enforce_storage_budget(uploaded_root=uploaded_root, generated_root=generated_root, target=target, payload_size=len(payload))
        atomic_write_bytes(target, payload)
        record = upsert_file_record(data_root=data_root, role=role, root=root, path=target, sha256=content_hash(payload))
    return {"file": record, "bytes_written": len(payload)}



def preview_text_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path, data_root: Path, max_chars: int | None) -> dict:
    if max_chars is not None and (max_chars <= 0 or max_chars > MAX_TEXT_PREVIEW_CHARS):
        raise StorageValidationError(f"max_chars must be between 1 and {MAX_TEXT_PREVIEW_CHARS}.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = upsert_file_record(data_root=data_root, role=role, root=root, path=path.resolve())
    effective_max_chars = MAX_TEXT_PREVIEW_CHARS if max_chars is None else max_chars
    cache_key = _text_preview_cache_key(record, effective_max_chars)
    cache = _load_text_preview_cache(data_root)
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        return {"file": record, "preview_text": cached, "cache_hit": True}
    preview_text = extract_text_preview(path, record["preview_kind"], effective_max_chars)
    cache[cache_key] = preview_text
    _write_text_preview_cache(data_root, cache)
    return {"file": record, "preview_text": preview_text, "cache_hit": False}



def preview_table_payload(*, role: str, relative_path: str, data_root: Path, uploaded_root: Path, generated_root: Path, max_rows: int | None, max_columns: int | None) -> dict:
    if max_rows is not None and (max_rows <= 0 or max_rows > MAX_TABLE_PREVIEW_ROWS):
        raise StorageValidationError(f"max_rows must be between 1 and {MAX_TABLE_PREVIEW_ROWS}.")
    if max_columns is not None and (max_columns <= 0 or max_columns > MAX_TABLE_PREVIEW_COLUMNS):
        raise StorageValidationError(f"max_columns must be between 1 and {MAX_TABLE_PREVIEW_COLUMNS}.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = upsert_file_record(data_root=data_root, role=role, root=root, path=path.resolve())
    if record["preview_kind"] != "spreadsheet" and record["extension"].lower() != ".csv":
        raise StorageValidationError("Table preview is only available for CSV and spreadsheet files.")
    effective_max_rows = MAX_TABLE_PREVIEW_ROWS if max_rows is None else max_rows
    effective_max_columns = MAX_TABLE_PREVIEW_COLUMNS if max_columns is None else max_columns
    table = extract_table_preview(path, record["preview_kind"], max_rows=effective_max_rows, max_columns=effective_max_columns)
    return {"file": record, "sheets": table["sheets"]}



def file_info_payload(*, role: str, relative_path: str, data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    return {"file": upsert_file_record(data_root=data_root, role=role, root=root, path=path.resolve())}



def update_markdown_file_payload(*, role: str, relative_path: str, content: object, data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    if not isinstance(content, str):
        raise StorageValidationError("content must be a string.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_MARKDOWN_EDIT_BYTES:
        raise StorageValidationError(f"Markdown content must be at most {MAX_MARKDOWN_EDIT_BYTES} bytes.")
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        path = resolve_storage_file(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        record = upsert_file_record(data_root=data_root, role=role, root=root, path=path.resolve())
        if record["preview_kind"] != "markdown":
            raise StorageValidationError("Only Markdown files can be edited in the Storage Markdown editor.")
        enforce_storage_budget(uploaded_root=uploaded_root, generated_root=generated_root, target=path, payload_size=len(encoded))
        atomic_write_bytes(path, encoded)
        return {
            "file": upsert_file_record(
                data_root=data_root,
                role=role,
                root=root,
                path=path.resolve(),
                sha256=content_hash(encoded),
            )
        }



def create_folder_payload(*, role: str, parent_relative_path: object, folder_name: object, data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        parent = resolve_storage_folder(
            role=role,
            relative_path=parent_relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        target = (parent / safe_folder_name(folder_name)).resolve()
        if root not in target.parents:
            raise StorageValidationError("Folder must stay inside the selected storage root.")
        if target.exists():
            raise StorageValidationError("A folder or file with that name already exists.")
        target.mkdir()
        return {"folder": upsert_directory_record(data_root=data_root, role=role, root=root, path=target)}


def read_folder_payload(*, role: str, relative_path: object, uploaded_root: Path, generated_root: Path) -> dict:
    folder = resolve_storage_folder(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    relative = "" if folder == root else folder.relative_to(root).as_posix()
    if relative and is_system_upload_folder(role=role, relative_path=relative):
        raise StorageValidationError("Folder is not visible in Storage.")
    record = folder_record(role=role, root=root, path=folder)
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    total_bytes = 0
    for path in files:
        total_bytes += path.stat().st_size
        if total_bytes > MAX_FOLDER_DOWNLOAD_BYTES:
            raise StorageValidationError(f"Folder downloads are limited to {MAX_FOLDER_DOWNLOAD_BYTES} bytes.")
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path in files:
            resolved_path = path.resolve()
            if resolved_path == root or root not in resolved_path.parents:
                continue
            zip_file.write(path, path.relative_to(folder).as_posix())
    file_name = f"{record['name'] or role}.zip"
    return {
        "folder": record,
        "content_base64": b64encode(archive.getvalue()).decode("ascii"),
        "content_type": "application/zip",
        "file_name": file_name,
    }


def delete_folder_payload(*, role: str, relative_path: object, data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        folder = resolve_storage_folder(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        if folder == root:
            raise StorageValidationError("Storage root folders cannot be deleted.")
        relative = folder.relative_to(root).as_posix()
        if is_system_upload_folder(role=role, relative_path=relative):
            raise StorageValidationError("Folder is not visible in Storage.")
        record = folder_record(role=role, root=root, path=folder)
        shutil.rmtree(folder)
        remove_folder_records(data_root=data_root, role=role, relative_path=relative)
        return {"deleted": True, "folder": record}



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



def rename_file_payload(*, role: str, relative_path: str, new_name: str, data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        source = resolve_storage_file(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        normalized_name = safe_file_name(new_name)
        target = source.with_name(normalized_name).resolve()
        if root not in target.parents:
            raise StorageValidationError("Renamed file must stay inside the selected storage root.")
        if target.exists() and target != source:
            raise StorageValidationError("A file with that name already exists.")
        if target == source:
            return {"file": upsert_file_record(data_root=data_root, role=role, root=root, path=source)}
        source.rename(target)
        return {"file": rename_file_record(data_root=data_root, role=role, root=root, old_relative_path=relative_path, new_path=target)}
