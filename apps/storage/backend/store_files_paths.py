"""Workspace storage path helpers for the Storage app."""

from __future__ import annotations

from base64 import b64decode, b64encode
import binascii
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
import mimetypes
import os
from pathlib import Path
import re
import tempfile

from errors import StorageValidationError
from inventory import (
    content_hash,
    preview_kind as inventory_preview_kind,
    upsert_file_record,
)
from limits import MAX_INLINE_READ_BYTES, MAX_INLINE_WRITE_BYTES
from local_storage_provider import LocalStorageProvider
from storage_catalog import StorageCatalog


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
WRITE_MODES = {"create", "overwrite", "upsert", "versioned"}


def safe_folder_relative_path(raw_path: object) -> Path:
    value = str(raw_path or "").strip().strip("/")
    if not value:
        return Path()
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageValidationError("folder path must stay inside the selected storage root.")
    return relative


def safe_relative_path(raw_path: str) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        raise StorageValidationError("relative_path is required.")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageValidationError("relative_path must stay inside the selected storage root.")
    return relative


def storage_root_for_role(*, role: str, uploaded_root: Path, generated_root: Path) -> Path:
    if role == "uploaded":
        return uploaded_root
    if role == "generated":
        return generated_root
    raise StorageValidationError(f"Unsupported file role `{role}`.")



def reference_from_payload(*, role: str, relative_path: str, workspace_relative_path: str) -> tuple[str, str]:
    normalized_role = str(role or "").strip()
    normalized_relative = str(relative_path or "").strip()
    workspace_relative = str(workspace_relative_path or "").strip()
    if normalized_role and normalized_relative:
        return normalized_role, normalized_relative
    if not workspace_relative:
        raise StorageValidationError("role and relative_path, or workspace_relative_path, are required.")
    parts = Path(workspace_relative).parts
    if len(parts) < 3 or parts[0] != "storage" or parts[1] not in FILE_ROLES:
        raise StorageValidationError("workspace_relative_path must start with storage/uploaded/ or storage/generated/.")
    return parts[1], Path(*parts[2:]).as_posix()



def safe_file_name(raw_name: str) -> str:
    value = " ".join(str(raw_name or "").strip().split())
    if not value or value in {".", ".."}:
        raise StorageValidationError("new_name is required.")
    if "/" in value or "\\" in value or "\x00" in value:
        raise StorageValidationError("new_name must be a file name, not a path.")
    return value


def normalize_write_mode(raw_mode: object, *, operation: str = "file.content.write") -> str:
    mode = str(raw_mode or "overwrite").strip().lower()
    if mode not in WRITE_MODES:
        raise StorageValidationError(
            "mode must be create, overwrite, upsert, or versioned.",
            operation=operation,
            allowed_values={"mode": sorted(WRITE_MODES)},
        )
    return mode


def prepare_write_target(*, root: Path, requested_target: Path, mode: str, operation: str) -> Path:
    target = requested_target.resolve()
    if target == root or root not in target.parents:
        raise StorageValidationError("File path escapes the selected storage root.", operation=operation)
    if target.exists() and not target.is_file():
        raise StorageValidationError("Target path is not a file.", operation=operation)
    if mode == "create" and target.exists():
        raise StorageValidationError("File already exists.", operation=operation)
    if mode == "overwrite" and not target.exists():
        raise StorageValidationError("File does not exist.", operation=operation)
    if mode == "versioned" and target.exists():
        return versioned_storage_path(target)
    return target


def versioned_storage_path(target: Path) -> Path:
    suffix = target.suffix
    stem = target.name[: -len(suffix)] if suffix else target.name
    parent = target.parent
    for index in range(2, 10_000):
        candidate = parent / f"{stem}.v{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise StorageValidationError("Could not allocate a versioned file name.")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def safe_folder_name(raw_name: object) -> str:
    value = safe_file_name(str(raw_name or ""))
    if "." == value or value.startswith("."):
        raise StorageValidationError("folder_name must be a visible folder name.")
    return value



def resolve_storage_file(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path) -> Path:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    candidate = (root / safe_relative_path(relative_path)).resolve()
    if candidate == root or root not in candidate.parents:
        raise StorageValidationError("File path escapes the selected storage root.")
    if not candidate.is_file():
        raise StorageValidationError("File does not exist.")
    return candidate



def resolve_storage_folder(*, role: str, relative_path: object, uploaded_root: Path, generated_root: Path, must_exist: bool = True) -> Path:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    relative = safe_folder_relative_path(relative_path)
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise StorageValidationError("Folder path escapes the selected storage root.")
    if must_exist and not candidate.is_dir():
        raise StorageValidationError("Folder does not exist.")
    return candidate



def preview_kind(content_type: str, suffix: str) -> str:
    return inventory_preview_kind(content_type, suffix)



def file_record(*, role: str, root: Path, path: Path, file_id: str | None = None, sha256: str | None = None) -> dict:
    relative = path.relative_to(root).as_posix()
    workspace_relative = f"storage/{role}/{relative}"
    stat = path.stat()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    path_id = f"{role}:{relative}"
    return {
        "id": file_id or path_id,
        "file_id": file_id or path_id,
        "path_id": path_id,
        "role": role,
        "name": path.name,
        "relative_path": relative,
        "workspace_relative_path": workspace_relative,
        "extension": path.suffix.lower(),
        "size_bytes": stat.st_size,
        "modified_at": modified,
        "content_type": content_type,
        "preview_kind": preview_kind(content_type, path.suffix),
        "sha256": sha256 or "",
    }



def folder_record(*, role: str, root: Path, path: Path) -> dict:
    relative = "" if path == root else path.relative_to(root).as_posix()
    name = path.name if relative else ("Uploaded" if role == "uploaded" else "Generated")
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    return {
        "id": f"{role}:{relative}/",
        "role": role,
        "name": name,
        "relative_path": relative,
        "workspace_relative_path": f"storage/{role}" + (f"/{relative}" if relative else ""),
        "modified_at": modified,
    }



def is_system_upload_folder(*, role: str, relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return role == "uploaded" and len(parts) == 1 and bool(UPLOAD_BUCKET_PATTERN.fullmatch(parts[0]))



def catalog_files_payload(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    sync: bool = False,
    query: str = "",
    role: str = "all",
    kind: str = "all",
    offset: int = 0,
    limit: int | None = None,
    sort_by: str = "modified_at",
    sort_direction: str = "desc",
    folder_path: str | None = None,
    file_ids: list[str] | None = None,
    workspace_relative_paths: list[str] | None = None,
) -> dict:
    with storage_write_lock(data_root):
        return _storage_catalog(uploaded_root=uploaded_root, generated_root=generated_root).catalog_files(
            data_root=data_root,
            sync=sync,
            query=query,
            role=role,
            kind=kind,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_direction=sort_direction,
            folder_path=folder_path,
            file_ids=file_ids,
            workspace_relative_paths=workspace_relative_paths,
        )


def list_files(*, data_root: Path, uploaded_root: Path, generated_root: Path) -> list[dict]:
    return catalog_files_payload(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)["files"]



def list_folders(*, data_root: Path, uploaded_root: Path, generated_root: Path, sync: bool = False) -> list[dict]:
    with storage_write_lock(data_root):
        return _storage_catalog(uploaded_root=uploaded_root, generated_root=generated_root).list_folders(data_root=data_root, sync=sync)


def _storage_catalog(*, uploaded_root: Path, generated_root: Path) -> StorageCatalog:
    return StorageCatalog(local_provider=LocalStorageProvider(uploaded_root=uploaded_root, generated_root=generated_root))



def read_file_payload(
    *,
    role: str,
    relative_path: str,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    max_bytes: int,
    return_handle: bool = False,
    include_content: bool = True,
    include_local_path: bool = False,
) -> dict:
    if max_bytes <= 0 or max_bytes > MAX_READ_BYTES:
        raise StorageValidationError(f"max_bytes must be between 1 and {MAX_READ_BYTES}.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    if include_content and path.stat().st_size > max_bytes:
        raise StorageValidationError("File is too large to read through Storage preview.")
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = upsert_file_record(data_root=data_root, role=role, root=root, path=path.resolve())
    payload = {"file": record}
    if include_content:
        payload["content_base64"] = b64encode(path.read_bytes()).decode("ascii")
    if return_handle:
        handle = {
            "kind": "workspace_storage_file",
            "role": role,
            "relative_path": record["relative_path"],
            "workspace_relative_path": record["workspace_relative_path"],
            "size_bytes": record["size_bytes"],
            "sha256": record.get("sha256") or hash_file(path),
        }
        if include_local_path:
            handle["local_path"] = str(path)
        payload["file_handle"] = handle
    return payload



def write_file_payload(
    *,
    role: str,
    relative_path: str,
    data_root: Path,
    content: object,
    content_base64: object,
    mode: object,
    uploaded_root: Path,
    generated_root: Path,
) -> dict:
    payload = write_content_bytes(content=content, content_base64=content_base64)
    write_mode = normalize_write_mode(mode)
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    requested_target = (root / safe_relative_path(relative_path)).resolve()
    with storage_write_lock(data_root):
        target = prepare_write_target(
            root=root,
            requested_target=requested_target,
            mode=write_mode,
            operation="file.content.write",
        )
        previous_path = requested_target if requested_target.exists() and requested_target.is_file() else None
        previous_sha256 = hash_file(previous_path) if previous_path and target == requested_target else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        enforce_storage_budget(uploaded_root=uploaded_root, generated_root=generated_root, target=target, payload_size=len(payload))
        atomic_write_bytes(target, payload)
        new_sha256 = content_hash(payload)
        record = upsert_file_record(
            data_root=data_root,
            role=role,
            root=root,
            path=target,
            sha256=new_sha256,
        )
    audit = {
        "operation": "file.content.write",
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


def write_content_bytes(*, content: object, content_base64: object) -> bytes:
    if content_base64 is not None:
        try:
            payload = b64decode(str(content_base64), validate=True)
        except (ValueError, binascii.Error) as error:
            raise StorageValidationError("content_base64 must be valid base64.") from error
    elif isinstance(content, str):
        payload = content.encode("utf-8")
    else:
        raise StorageValidationError("content or content_base64 is required.")
    if len(payload) > MAX_WRITE_BYTES:
        raise StorageValidationError(f"Written file content must be at most {MAX_WRITE_BYTES} bytes.")
    return payload


def atomic_write_bytes(target: Path, payload: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=target.parent, prefix=f".maverick-storage-write-{target.name}.", suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def enforce_storage_budget(*, uploaded_root: Path, generated_root: Path, target: Path, payload_size: int) -> None:
    max_storage_bytes = _configured_storage_budget()
    if max_storage_bytes is None:
        return
    existing_size = target.stat().st_size if target.exists() and target.is_file() else 0
    projected = _stored_storage_bytes(uploaded_root) + _stored_storage_bytes(generated_root) - existing_size + payload_size
    if projected > max_storage_bytes:
        raise StorageValidationError("workspace_storage_quota_exceeded")


@contextmanager
def storage_write_lock(data_root: Path):
    data_root.mkdir(parents=True, exist_ok=True)
    lock_path = data_root / ".storage-write.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _configured_storage_budget() -> int | None:
    raw_value = os.environ.get("MAVERICK_STORAGE_MAX_BYTES") or os.environ.get("MAVERICK_WORKSPACE_MAX_STORAGE_BYTES")
    if raw_value is None or raw_value == "":
        return None
    try:
        value = int(raw_value)
    except ValueError as error:
        raise StorageValidationError("Storage byte budget must be an integer.") from error
    if value < 0:
        raise StorageValidationError("Storage byte budget must not be negative.")
    return value


def _stored_storage_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    resolved_root = root.resolve()
    for path in resolved_root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        resolved_path = path.resolve()
        if resolved_root in resolved_path.parents:
            total += resolved_path.stat().st_size
    return total
