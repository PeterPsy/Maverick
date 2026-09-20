"""Stable file inventory for the Storage app."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re
from uuid import uuid4
from typing import Any

from file_cache_policy import stable_source_version
from storage_provider_model import (
    FILE_ROLES,
    GOOGLE_DRIVE_PROVIDER,
    LOCAL_PROVIDER,
    normalize_capabilities,
    normalize_provider,
    normalize_remote_locator,
)
from storage_mime import guess_content_type, normalize_content_type


INVENTORY_FILE = "files.json"
INVENTORY_SCHEMA_VERSION = "1"
FILE_ID_PATTERN = re.compile(r"^file_[0-9a-f]{32}$")
CATALOG_SORT_FIELDS = {"modified_at", "relative_path", "name", "size_bytes", "preview_kind"}
PREVIEW_KIND_ORDER = ("image", "video", "audio", "pdf", "document", "presentation", "spreadsheet", "markdown", "text", "file")
STORAGE_TEMP_PREFIX = ".maverick-storage-write-"
UPLOAD_BUCKET_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)



def preview_kind(content_type: str, suffix: str) -> str:
    content_type = normalize_content_type(content_type, suffix=suffix)
    media_type = content_type.split(";", 1)[0].lower()
    normalized_suffix = suffix.lower()
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("video/"):
        return "video"
    if media_type.startswith("audio/"):
        return "audio"
    if normalized_suffix == ".md":
        return "markdown"
    if normalized_suffix in {".doc", ".docx", ".odt", ".rtf"}:
        return "document"
    if normalized_suffix in {".ppt", ".pptx", ".odp", ".key"}:
        return "presentation"
    if normalized_suffix in {".xls", ".xlsx", ".ods", ".numbers"}:
        return "spreadsheet"
    if media_type.startswith("text/") or normalized_suffix in {".json", ".csv", ".log", ".py", ".ts", ".tsx", ".txt"}:
        return "text"
    if media_type == "application/pdf":
        return "pdf"
    return "file"


def parse_file_reference(value: str) -> tuple[str, str] | None:
    if value.startswith("storage/"):
        parts = Path(value).parts
        if len(parts) >= 3 and parts[0] == "storage" and parts[1] in FILE_ROLES:
            return parts[1], Path(*parts[2:]).as_posix()
        return None
    role, separator, relative_path = value.partition(":")
    if separator and role in FILE_ROLES and relative_path:
        return role, relative_path
    return None


def content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_file_id(value: object) -> bool:
    return bool(FILE_ID_PATTERN.fullmatch(str(value or "")))


def _normalize_entry(item: dict[str, Any]) -> dict[str, Any]:
    role = str(item.get("role") or "")
    relative_path = str(item.get("relative_path") or "")
    provider = normalize_provider(item.get("provider"), role=role)
    file_id = str(item.get("file_id") or item.get("id") or "")
    if not stable_file_id(file_id):
        file_id = f"file_{uuid4().hex}"
    if provider == LOCAL_PROVIDER:
        workspace_relative_path = f"storage/{role}/{relative_path}" if role in FILE_ROLES and relative_path else str(item.get("workspace_relative_path") or "")
        path_id = f"{role}:{relative_path}" if role in FILE_ROLES and relative_path else ""
        name = str(item.get("name") or Path(relative_path).name)
        extension = str(item.get("extension") or Path(relative_path).suffix.lower())
        display_path = workspace_relative_path
        connection_id = ""
        drive_file_id = ""
        remote_locator: dict[str, Any] = {}
        sync_status = str(item.get("sync_status") or "synced")
    else:
        connection_id = str(item.get("connection_id") or "")
        raw_drive_file_id = str(item.get("drive_file_id") or "")
        remote_locator = normalize_remote_locator(
            item.get("remote_locator"),
            provider=provider,
            drive_file_id=raw_drive_file_id,
        )
        drive_file_id = str(remote_locator.get("drive_file_id") or raw_drive_file_id) if provider == GOOGLE_DRIVE_PROVIDER else raw_drive_file_id
        role = ""
        relative_path = ""
        workspace_relative_path = ""
        path_id = ""
        display_path = str(item.get("display_path") or item.get("remote_path") or item.get("name") or "")
        name = str(item.get("name") or Path(display_path).name or drive_file_id or file_id)
        extension = str(item.get("extension") or Path(name).suffix.lower())
        sync_status = str(item.get("sync_status") or "unknown")
    content_type = normalize_content_type(item.get("content_type"), file_name=name, suffix=extension)
    computed_preview_kind = preview_kind(content_type, extension)
    stored_preview_kind = str(item.get("preview_kind") or "")
    normalized_preview_kind = computed_preview_kind if stored_preview_kind in {"", "file"} and computed_preview_kind != "file" else stored_preview_kind or computed_preview_kind
    return {
        "id": file_id,
        "file_id": file_id,
        "path_id": path_id,
        "provider": provider,
        "connection_id": connection_id,
        "drive_file_id": drive_file_id,
        "remote_locator": remote_locator,
        "display_path": display_path,
        "role": role,
        "name": name,
        "relative_path": relative_path,
        "workspace_relative_path": workspace_relative_path,
        "extension": extension,
        "size_bytes": int(item.get("size_bytes") or 0),
        "modified_at": str(item.get("modified_at") or ""),
        "content_type": content_type,
        "preview_kind": normalized_preview_kind,
        "sha256": str(item.get("sha256") or ""),
        "etag_or_version": str(item.get("etag_or_version") or item.get("source_version") or ""),
        "source_version": str(item.get("source_version") or ""),
        "capabilities": normalize_capabilities(item.get("capabilities"), provider=provider),
        "sync_status": sync_status,
        "indexed": bool(item.get("indexed") or False),
        "stale": bool(item.get("stale") or False),
        "index_status": str(item.get("index_status") or ("stale" if item.get("stale") else "not_indexed")),
        "indexed_at": str(item.get("indexed_at") or ""),
        "indexed_source_version": str(item.get("indexed_source_version") or ""),
        "memory_node_id": str(item.get("memory_node_id") or ""),
        "memory_external_ref_id": str(item.get("memory_external_ref_id") or ""),
        "memory_source_version_id": str(item.get("memory_source_version_id") or ""),
        "status": str(item.get("status") or "active"),
        "created_at": str(item.get("created_at") or ""),
        "updated_at": str(item.get("updated_at") or ""),
        "deleted_at": str(item.get("deleted_at") or ""),
    }


def _normalize_directory_entry(item: dict[str, Any]) -> dict[str, Any]:
    role = str(item.get("role") or "")
    relative_path = str(item.get("relative_path") or "")
    provider = normalize_provider(item.get("provider"), role=role)
    name = str(item.get("name") or Path(relative_path).name or ("Uploaded" if role == "uploaded" else "Generated"))
    if provider == LOCAL_PROVIDER:
        workspace_relative_path = f"storage/{role}" + (f"/{relative_path}" if relative_path else "") if role in FILE_ROLES else ""
        display_path = workspace_relative_path
        connection_id = ""
        remote_locator: dict[str, Any] = {}
    else:
        role = ""
        relative_path = ""
        workspace_relative_path = ""
        display_path = str(item.get("display_path") or name)
        connection_id = str(item.get("connection_id") or "")
        remote_locator = normalize_remote_locator(item.get("remote_locator"), provider=provider)
    try:
        mtime_ns = int(item.get("mtime_ns") or 0)
    except (TypeError, ValueError):
        mtime_ns = 0
    return {
        "id": f"{role}:{relative_path}/",
        "provider": provider,
        "connection_id": connection_id,
        "remote_locator": remote_locator,
        "display_path": display_path,
        "role": role,
        "name": name,
        "relative_path": relative_path,
        "workspace_relative_path": workspace_relative_path,
        "modified_at": str(item.get("modified_at") or ""),
        "mtime_ns": mtime_ns,
        "capabilities": normalize_capabilities(item.get("capabilities"), provider=provider),
        "sync_status": str(item.get("sync_status") or ("synced" if provider == LOCAL_PROVIDER else "unknown")),
        "indexed": bool(item.get("indexed") or False),
        "stale": bool(item.get("stale") or False),
        "index_status": str(item.get("index_status") or ("stale" if item.get("stale") else "not_indexed")),
        "status": str(item.get("status") or "active"),
        "updated_at": str(item.get("updated_at") or ""),
        "deleted_at": str(item.get("deleted_at") or ""),
    }


def _entry_for_path(
    *,
    role: str,
    root: Path,
    path: Path,
    file_id: str | None,
    sha256: str | None,
    created_at: str,
    status: str,
    stat=None,
) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    stat = path.stat() if stat is None else stat
    content_type = guess_content_type(path.name)
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    stable_id = file_id if file_id and stable_file_id(file_id) else f"file_{uuid4().hex}"
    return {
        "id": stable_id,
        "file_id": stable_id,
        "path_id": f"{role}:{relative}",
        "provider": LOCAL_PROVIDER,
        "connection_id": "",
        "drive_file_id": "",
        "remote_locator": {},
        "display_path": f"storage/{role}/{relative}",
        "role": role,
        "name": path.name,
        "relative_path": relative,
        "workspace_relative_path": f"storage/{role}/{relative}",
        "extension": path.suffix.lower(),
        "size_bytes": stat.st_size,
        "modified_at": modified,
        "content_type": content_type,
        "preview_kind": preview_kind(content_type, path.suffix),
        "sha256": sha256 or "",
        "etag_or_version": "",
        "capabilities": normalize_capabilities({}, provider=LOCAL_PROVIDER),
        "sync_status": "synced",
        "indexed": False,
        "stale": False,
        "index_status": "not_indexed",
        "indexed_at": "",
        "indexed_source_version": "",
        "memory_node_id": "",
        "memory_external_ref_id": "",
        "memory_source_version_id": "",
        "status": status,
        "created_at": created_at,
        "updated_at": _timestamp(),
        "deleted_at": "",
    }


def _directory_entry_for_path(*, role: str, root: Path, path: Path, stat=None) -> dict[str, Any]:
    relative = "" if path == root else path.relative_to(root).as_posix()
    stat = path.stat() if stat is None else stat
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    return {
        "id": f"{role}:{relative}/",
        "provider": LOCAL_PROVIDER,
        "connection_id": "",
        "remote_locator": {},
        "display_path": f"storage/{role}" + (f"/{relative}" if relative else ""),
        "role": role,
        "name": path.name if relative else ("Uploaded" if role == "uploaded" else "Generated"),
        "relative_path": relative,
        "workspace_relative_path": f"storage/{role}" + (f"/{relative}" if relative else ""),
        "modified_at": modified,
        "mtime_ns": stat.st_mtime_ns,
        "capabilities": normalize_capabilities({}, provider=LOCAL_PROVIDER),
        "sync_status": "synced",
        "indexed": False,
        "stale": False,
        "index_status": "not_indexed",
        "status": "active",
        "updated_at": _timestamp(),
        "deleted_at": "",
    }


def _public_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["file_id"],
        "file_id": item["file_id"],
        "path_id": item["path_id"],
        "provider": item.get("provider", LOCAL_PROVIDER),
        "connection_id": item.get("connection_id", ""),
        "drive_file_id": item.get("drive_file_id", ""),
        "remote_locator": item.get("remote_locator", {}),
        "display_path": item.get("display_path", item.get("workspace_relative_path", "")),
        "role": item["role"],
        "name": item["name"],
        "relative_path": item["relative_path"],
        "workspace_relative_path": item["workspace_relative_path"],
        "extension": item["extension"],
        "size_bytes": item["size_bytes"],
        "modified_at": item["modified_at"],
        "created_at": item.get("created_at", ""),
        "content_type": item["content_type"],
        "preview_kind": item["preview_kind"],
        "sha256": item.get("sha256", ""),
        "etag_or_version": item.get("etag_or_version", ""),
        "source_version": stable_source_version(item),
        "capabilities": item.get("capabilities", normalize_capabilities({}, provider=str(item.get("provider") or LOCAL_PROVIDER))),
        "sync_status": item.get("sync_status", "synced"),
        "indexed": bool(item.get("indexed") or False),
        "stale": bool(item.get("stale") or False),
        "index_status": item.get("index_status", "not_indexed"),
        "indexed_at": item.get("indexed_at", ""),
        "indexed_source_version": item.get("indexed_source_version", ""),
        "memory_node_id": item.get("memory_node_id", ""),
        "memory_external_ref_id": item.get("memory_external_ref_id", ""),
        "memory_source_version_id": item.get("memory_source_version_id", ""),
        "status": item.get("status", "active"),
    }


def _public_folder_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "provider": item.get("provider", LOCAL_PROVIDER),
        "connection_id": item.get("connection_id", ""),
        "remote_locator": item.get("remote_locator", {}),
        "display_path": item.get("display_path", item.get("workspace_relative_path", "")),
        "role": item["role"],
        "name": item["name"],
        "relative_path": item["relative_path"],
        "workspace_relative_path": item["workspace_relative_path"],
        "modified_at": item["modified_at"],
        "capabilities": item.get("capabilities", normalize_capabilities({}, provider=str(item.get("provider") or LOCAL_PROVIDER))),
        "sync_status": item.get("sync_status", "synced"),
        "indexed": bool(item.get("indexed") or False),
        "stale": bool(item.get("stale") or False),
        "index_status": item.get("index_status", "not_indexed"),
        "status": item.get("status", "active"),
    }


def _deleted_entry(item: dict[str, Any], *, now: str) -> dict[str, Any]:
    updated = dict(item)
    updated["status"] = "deleted"
    updated["updated_at"] = now
    updated["deleted_at"] = now
    return _normalize_entry(updated)


def _deleted_directory_entry(item: dict[str, Any], *, now: str) -> dict[str, Any]:
    updated = dict(item)
    updated["status"] = "deleted"
    updated["updated_at"] = now
    updated["deleted_at"] = now
    return _normalize_directory_entry(updated)


def _existing_file_id(existing: dict[str, Any] | None) -> str | None:
    if not existing:
        return None
    file_id = str(existing.get("file_id") or existing.get("id") or "")
    return file_id if stable_file_id(file_id) else None


def _preserve_remote_index_state(*, existing: dict[str, Any] | None, entry: dict[str, Any]) -> dict[str, Any]:
    if entry.get("provider") == LOCAL_PROVIDER or existing is None:
        return entry
    updated = dict(entry)
    was_indexed = bool(existing.get("indexed") or False)
    existing_stale = bool(existing.get("stale") or False)
    old_version = str(existing.get("etag_or_version") or "")
    new_version = str(entry.get("etag_or_version") or "")
    removed_or_inaccessible = str(entry.get("status") or "active") != "active"
    successful_index = (
        bool(entry.get("indexed"))
        and str(entry.get("index_status") or "") == "indexed"
        and not bool(entry.get("stale"))
        and not removed_or_inaccessible
    )
    version_changed = bool(was_indexed and old_version and new_version and old_version != new_version)
    stale = False if successful_index else existing_stale or bool(entry.get("stale") or False) or version_changed or removed_or_inaccessible
    updated["indexed"] = was_indexed or bool(entry.get("indexed") or False)
    updated["stale"] = stale
    for key in ("indexed_at", "indexed_source_version", "memory_node_id", "memory_external_ref_id", "memory_source_version_id"):
        if not str(updated.get(key) or "") and str(existing.get(key) or ""):
            updated[key] = existing.get(key)
    if stale:
        updated["index_status"] = "stale"
    elif successful_index:
        updated["index_status"] = "indexed"
        updated["indexed_source_version"] = str(entry.get("indexed_source_version") or entry.get("etag_or_version") or existing.get("indexed_source_version") or "")
    elif updated["indexed"]:
        updated["index_status"] = str(existing.get("index_status") or "indexed")
    else:
        updated["index_status"] = str(entry.get("index_status") or "not_indexed")
    return _normalize_entry(updated)


def _timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()
