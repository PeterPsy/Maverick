"""Workspace storage record actions for the Storage app."""

from __future__ import annotations

from base64 import b64encode
from contextlib import contextmanager
import fcntl
from io import BytesIO
from pathlib import Path
import re
import shutil
import tempfile
import time
import zipfile
from xml.etree import ElementTree

from core.app_sdk.storage import read_json_state, write_json_state
from errors import StorageValidationError
from inventory import content_hash, remove_folder_records, rename_file_record, upsert_directory_record, upsert_file_record
from limits import MAX_INLINE_READ_BYTES, MAX_INLINE_WRITE_BYTES, MAX_STORAGE_FILE_TRANSFER_BYTES, MAX_STORAGE_TRANSIENT_TRANSFER_BYTES
from store_files_paths import (
    atomic_write_bytes,
    enforce_storage_budget,
    folder_record,
    hash_file,
    is_system_upload_folder,
    normalize_write_mode,
    prepare_write_target,
    resolve_storage_file,
    resolve_storage_folder,
    safe_file_name,
    safe_folder_name,
    storage_write_lock,
    storage_root_for_role,
    write_content_bytes,
)
from storage_reference_resolver import StorageReferenceResolver
from store_files_view import text_preview_cache_path
from text_preview import (
    MAX_TABLE_PREVIEW_COLUMNS,
    MAX_TABLE_PREVIEW_ROWS,
    MAX_TEXT_PREVIEW_CHARS,
    extract_table_preview,
    extract_text_content,
    extract_text_preview,
    text_content_supported,
)


SCHEMA_VERSION = "1"
MAX_READ_BYTES = MAX_INLINE_READ_BYTES
FILE_ROLES = {"uploaded", "generated"}
UPLOAD_BUCKET_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
VIEW_FILTER_ROLES = {"all", *FILE_ROLES}
VIEW_FILTER_KINDS = {"all", "image", "video", "audio", "markdown", "text", "pdf", "document", "presentation", "spreadsheet", "file"}
MAX_VIEW_QUERY_CHARS = 200
MAX_CUSTOM_VIEW_TITLE_CHARS = 140
MAX_CUSTOM_VIEW_FILES = 500
MAX_TEXT_PREVIEW_CACHE_ENTRIES = 200
MAX_MARKDOWN_EDIT_BYTES = 2 * 1024 * 1024
MAX_WRITE_BYTES = MAX_INLINE_WRITE_BYTES
MAX_FOLDER_DOWNLOAD_BYTES = MAX_STORAGE_FILE_TRANSFER_BYTES
MAX_INLINE_FOLDER_DOWNLOAD_BYTES = MAX_INLINE_READ_BYTES
FOLDER_DOWNLOAD_CACHE_SECONDS = 2 * 60 * 60


def upload_file_payload(
    *,
    role: str,
    folder_relative_path: object,
    file_name: object,
    content_base64: object,
    mode: object = "create",
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
) -> dict:
    payload = write_content_bytes(content=None, content_base64=content_base64)
    write_mode = normalize_write_mode(mode, operation="upload_file")
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        folder = resolve_storage_folder(
            role=role,
            relative_path=folder_relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        requested_target = (folder / safe_file_name(str(file_name or ""))).resolve()
        target = prepare_write_target(
            root=root,
            requested_target=requested_target,
            mode=write_mode,
            operation="upload_file",
        )
        previous_sha256 = hash_file(target) if target.exists() and target.is_file() else ""
        enforce_storage_budget(uploaded_root=uploaded_root, generated_root=generated_root, target=target, payload_size=len(payload))
        atomic_write_bytes(target, payload)
        new_sha256 = content_hash(payload)
        record = upsert_file_record(data_root=data_root, role=role, root=root, path=target, sha256=new_sha256)
    audit = {
        "operation": "upload_file",
        "requested_mode": write_mode,
        "effective_mode": "create" if not previous_sha256 else "overwrite",
        "requested_workspace_relative_path": f"storage/{role}/{requested_target.relative_to(root).as_posix()}",
        "workspace_relative_path": record["workspace_relative_path"],
        "previous_sha256": previous_sha256,
        "sha256": new_sha256,
        "bytes_written": len(payload),
        "replaced": bool(previous_sha256 and target == requested_target),
    }
    return {"file": record, "bytes_written": len(payload), "audit": audit}



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



def read_text_payload(
    *,
    role: str,
    relative_path: str,
    uploaded_root: Path,
    generated_root: Path,
    data_root: Path,
    offset: int,
    max_chars: int | None,
) -> dict:
    if offset < 0:
        raise StorageValidationError("offset must not be negative.")
    if max_chars is not None and max_chars <= 0:
        raise StorageValidationError("max_chars must be positive.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = upsert_file_record(data_root=data_root, role=role, root=root, path=path.resolve())
    if not text_content_supported(path, record["preview_kind"]):
        raise StorageValidationError("Text read is only available for text, Markdown, DOCX, PPTX, XLSX, and ODT files.")
    try:
        text = extract_text_content(path, record["preview_kind"])
    except (ValueError, KeyError, ElementTree.ParseError, zipfile.BadZipFile, OSError, UnicodeDecodeError) as error:
        raise StorageValidationError(f"Text could not be extracted: {error}") from error
    text_char_count = len(text)
    start = min(offset, text_char_count)
    range_end = text_char_count if max_chars is None else min(text_char_count, start + max_chars)
    return {
        "file": record,
        "text": text[start:range_end],
        "text_char_count": text_char_count,
        "offset": start,
        "max_chars": max_chars,
        "range_end": range_end,
        "has_more": range_end < text_char_count,
        "next_offset": range_end if range_end < text_char_count else None,
        "complete": start == 0 and range_end == text_char_count,
    }


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


def file_info_by_id_payload(*, file_id: str, data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    resolver = StorageReferenceResolver(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)
    return {"file": resolver.require_file(file_id)}



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


def read_folder_payload(
    *,
    role: str,
    relative_path: object,
    uploaded_root: Path,
    generated_root: Path,
    data_root: Path | None = None,
    stream_download: bool = False,
) -> dict:
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
    max_download_bytes = MAX_FOLDER_DOWNLOAD_BYTES if stream_download else MAX_INLINE_FOLDER_DOWNLOAD_BYTES
    for path in files:
        total_bytes += path.stat().st_size
        if total_bytes > max_download_bytes:
            raise StorageValidationError(f"Folder downloads are limited to {max_download_bytes} bytes.")
    file_name = f"{record['name'] or role}.zip"
    if stream_download:
        if data_root is None:
            raise StorageValidationError("data_root is required for streamed folder downloads.")
        download_root = _folder_download_root(data_root)
        with _folder_download_temp_lock(download_root):
            archive_path = _folder_download_archive_path(download_root, file_name)
            try:
                _enforce_folder_download_temp_budget(download_root, incoming_bytes=total_bytes)
                _write_folder_archive(archive_path=archive_path, folder=folder, root=root, files=files)
                archive_size = archive_path.stat().st_size
                if archive_size > MAX_FOLDER_DOWNLOAD_BYTES:
                    raise StorageValidationError(f"Folder downloads are limited to {MAX_FOLDER_DOWNLOAD_BYTES} bytes.")
                _enforce_folder_download_temp_budget(download_root, incoming_bytes=0)
            except Exception:
                archive_path.unlink(missing_ok=True)
                raise
        return {
            "folder": record,
            "file_response": {
                "path": str(archive_path),
                "content_type": "application/zip",
                "file_name": file_name,
                "download": True,
                "delete_after_send": True,
                "cache_control": "private, no-store",
            },
        }
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        _write_folder_archive_entries(zip_file=zip_file, folder=folder, root=root, files=files)
    return {
        "folder": record,
        "content_base64": b64encode(archive.getvalue()).decode("ascii"),
        "content_type": "application/zip",
        "file_name": file_name,
    }


def _folder_download_root(data_root: Path) -> Path:
    download_root = data_root / "run" / "folder_downloads"
    download_root.mkdir(parents=True, exist_ok=True)
    return download_root


@contextmanager
def _folder_download_temp_lock(download_root: Path):
    download_root.mkdir(parents=True, exist_ok=True)
    lock_path = download_root / ".folder-download.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _folder_download_archive_path(download_root: Path, file_name: str) -> Path:
    cutoff = time.time() - FOLDER_DOWNLOAD_CACHE_SECONDS
    for path in download_root.glob("*.zip"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue
    safe_name = (safe_file_name(file_name).removesuffix(".zip") or "folder")[:80].rstrip(" .") or "folder"
    handle = tempfile.NamedTemporaryFile("wb", dir=download_root, prefix=f"{safe_name}.", suffix=".zip", delete=False)
    handle.close()
    return Path(handle.name)


def _enforce_folder_download_temp_budget(download_root: Path, *, incoming_bytes: int) -> None:
    _prune_folder_download_temp_files(download_root)
    total = 0
    for path in [*download_root.glob("*.zip"), *download_root.glob("*.tmp")]:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    if total + max(0, incoming_bytes) > MAX_STORAGE_TRANSIENT_TRANSFER_BYTES:
        raise StorageValidationError("Temporary folder download space is exhausted; try again after active downloads finish.")


def _prune_folder_download_temp_files(download_root: Path) -> None:
    cutoff = time.time() - FOLDER_DOWNLOAD_CACHE_SECONDS
    for pattern in ("*.zip", "*.tmp"):
        for path in download_root.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue


def _write_folder_archive(*, archive_path: Path, folder: Path, root: Path, files: list[Path]) -> None:
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            _write_folder_archive_entries(zip_file=zip_file, folder=folder, root=root, files=files)
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


def _write_folder_archive_entries(*, zip_file: zipfile.ZipFile, folder: Path, root: Path, files: list[Path]) -> None:
    for path in files:
        resolved_path = path.resolve()
        if resolved_path == root or root not in resolved_path.parents:
            continue
        zip_file.write(path, path.relative_to(folder).as_posix())


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
