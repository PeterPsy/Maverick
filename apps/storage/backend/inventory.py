"""Stable file inventory for the Storage app."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import mimetypes
from pathlib import Path
import re
from uuid import uuid4
from typing import Any

from core.app_sdk.storage import read_json_state, update_json_state
from errors import StorageValidationError


INVENTORY_FILE = "files.json"
INVENTORY_SCHEMA_VERSION = "1"
FILE_ID_PATTERN = re.compile(r"^file_[0-9a-f]{32}$")
FILE_ROLES = {"uploaded", "generated"}
CATALOG_SORT_FIELDS = {"modified_at", "relative_path", "name", "size_bytes", "preview_kind"}
STORAGE_TEMP_PREFIX = ".maverick-storage-write-"
UPLOAD_BUCKET_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def inventory_path(data_root: Path) -> Path:
    return data_root / INVENTORY_FILE


def preview_kind(content_type: str, suffix: str) -> str:
    normalized_suffix = suffix.lower()
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    if normalized_suffix == ".md":
        return "markdown"
    if normalized_suffix in {".doc", ".docx", ".odt", ".rtf"}:
        return "document"
    if normalized_suffix in {".ppt", ".pptx", ".odp", ".key"}:
        return "presentation"
    if normalized_suffix in {".xls", ".xlsx", ".ods", ".numbers"}:
        return "spreadsheet"
    if content_type.startswith("text/") or normalized_suffix in {".json", ".csv", ".log", ".py", ".ts", ".tsx", ".txt"}:
        return "text"
    if content_type == "application/pdf":
        return "pdf"
    return "file"


def load_inventory(data_root: Path) -> dict[str, Any]:
    payload = read_json_state(data_root, INVENTORY_FILE, _empty_inventory())
    return _normalize_inventory(payload)


def ensure_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    if not inventory_path(data_root).exists():
        return sync_inventory(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)
    return refresh_inventory(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)


def sync_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    """Reconcile the inventory with the filesystem by scanning storage roots."""

    def updater(payload: dict[str, Any]) -> dict[str, Any]:
        inventory = _normalize_inventory(payload)
        return _sync_inventory_payload(inventory, uploaded_root=uploaded_root, generated_root=generated_root)

    return update_json_state(data_root, INVENTORY_FILE, updater, _empty_inventory())


def refresh_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    """Refresh known files and discover direct children of changed directories."""

    def updater(payload: dict[str, Any]) -> dict[str, Any]:
        inventory = _normalize_inventory(payload)
        if not inventory["directories"]:
            return _sync_inventory_payload(inventory, uploaded_root=uploaded_root, generated_root=generated_root)
        return _refresh_inventory_payload(inventory, uploaded_root=uploaded_root, generated_root=generated_root)

    return update_json_state(data_root, INVENTORY_FILE, updater, _empty_inventory())


def refresh_known_files(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    return refresh_inventory(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)


def list_inventory_files(
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
) -> dict[str, Any]:
    inventory = sync_inventory(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root) if sync else ensure_inventory(
        data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    files = [_public_record(item) for item in inventory["files"] if item.get("status") == "active"]
    files = _filter_records(
        files,
        query=query,
        role=role,
        kind=kind,
        folder_path=folder_path,
        file_ids=file_ids,
        workspace_relative_paths=workspace_relative_paths,
    )
    files = _sort_records(files, sort_by=sort_by, sort_direction=sort_direction)
    total = len(files)
    page = files[offset:] if limit is None else files[offset : offset + limit]
    return {
        "files": page,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(page) < total,
        },
        "inventory": {"updated_at": inventory.get("updated_at", ""), "schema_version": INVENTORY_SCHEMA_VERSION},
    }


def catalog_inventory_payload(
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
) -> dict[str, Any]:
    inventory = sync_inventory(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root) if sync else ensure_inventory(
        data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    files = [_public_record(item) for item in inventory["files"] if item.get("status") == "active"]
    files = _filter_records(
        files,
        query=query,
        role=role,
        kind=kind,
        folder_path=folder_path,
        file_ids=file_ids,
        workspace_relative_paths=workspace_relative_paths,
    )
    files = _sort_records(files, sort_by=sort_by, sort_direction=sort_direction)
    total = len(files)
    page = files[offset:] if limit is None else files[offset : offset + limit]
    return {
        "files": page,
        "folders": _folders_from_inventory(inventory),
        "pagination": {
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(page) < total,
        },
        "inventory": {"updated_at": inventory.get("updated_at", ""), "schema_version": INVENTORY_SCHEMA_VERSION},
    }


def list_inventory_folders(*, data_root: Path, uploaded_root: Path, generated_root: Path, sync: bool = False) -> list[dict[str, Any]]:
    inventory = sync_inventory(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root) if sync else ensure_inventory(
        data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    return _folders_from_inventory(inventory)


def upsert_file_record(
    *,
    data_root: Path,
    role: str,
    root: Path,
    path: Path,
    sha256: str | None = None,
    preserve_path_id: bool = True,
) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_root not in resolved_path.parents or not resolved_path.is_file():
        raise StorageValidationError("File does not exist.")
    relative_path = resolved_path.relative_to(resolved_root).as_posix()
    captured: dict[str, Any] = {}

    def updater(payload: dict[str, Any]) -> dict[str, Any]:
        inventory = _normalize_inventory(payload)
        existing = _find_active_by_path(inventory["files"], role=role, relative_path=relative_path) if preserve_path_id else None
        now = _timestamp()
        entry = _entry_for_path(
            role=role,
            root=resolved_root,
            path=resolved_path,
            file_id=_existing_file_id(existing),
            sha256=sha256 if sha256 is not None else _preserved_hash(existing=existing, path=resolved_path),
            created_at=str(existing.get("created_at") or now) if existing else now,
            status="active",
        )
        inventory["files"] = _replace_entry(inventory["files"], entry)
        inventory["directories"] = _replace_directories(
            inventory["directories"],
            _directory_chain_for_path(role=role, root=resolved_root, path=resolved_path.parent),
        )
        inventory["updated_at"] = now
        captured.update(_public_record(entry))
        return inventory

    update_json_state(data_root, INVENTORY_FILE, updater, _empty_inventory())
    return captured


def rename_file_record(
    *,
    data_root: Path,
    role: str,
    root: Path,
    old_relative_path: str,
    new_path: Path,
) -> dict[str, Any]:
    return _move_inventory_record(
        data_root=data_root,
        role=role,
        root=root,
        old_relative_path=old_relative_path,
        new_path=new_path,
    )


def move_file_record(
    *,
    data_root: Path,
    role: str,
    root: Path,
    old_relative_path: str,
    new_path: Path,
) -> dict[str, Any]:
    return _move_inventory_record(
        data_root=data_root,
        role=role,
        root=root,
        old_relative_path=old_relative_path,
        new_path=new_path,
    )


def remove_file_record(*, data_root: Path, role: str, relative_path: str) -> None:
    def updater(payload: dict[str, Any]) -> dict[str, Any]:
        inventory = _normalize_inventory(payload)
        now = _timestamp()
        next_files: list[dict[str, Any]] = []
        for item in inventory["files"]:
            if item.get("status") == "active" and item.get("role") == role and item.get("relative_path") == relative_path:
                next_files.append(_deleted_entry(item, now=now))
            else:
                next_files.append(item)
        inventory["files"] = _dedupe_by_file_id(next_files)
        inventory["updated_at"] = now
        return inventory

    update_json_state(data_root, INVENTORY_FILE, updater, _empty_inventory())


def remove_folder_records(*, data_root: Path, role: str, relative_path: str) -> None:
    prefix = relative_path.strip("/")
    def updater(payload: dict[str, Any]) -> dict[str, Any]:
        inventory = _normalize_inventory(payload)
        now = _timestamp()
        next_files: list[dict[str, Any]] = []
        next_directories: list[dict[str, Any]] = []
        for item in inventory["files"]:
            item_path = str(item.get("relative_path") or "")
            inside_folder = item.get("role") == role and item.get("status") == "active" and (item_path == prefix or item_path.startswith(f"{prefix}/"))
            next_files.append(_deleted_entry(item, now=now) if inside_folder else item)
        for item in inventory["directories"]:
            item_path = str(item.get("relative_path") or "")
            inside_folder = item.get("role") == role and item.get("status") == "active" and (item_path == prefix or item_path.startswith(f"{prefix}/"))
            next_directories.append(_deleted_directory_entry(item, now=now) if inside_folder else item)
        inventory["files"] = _dedupe_by_file_id(next_files)
        inventory["directories"] = _dedupe_directories(next_directories)
        inventory["updated_at"] = now
        return inventory

    update_json_state(data_root, INVENTORY_FILE, updater, _empty_inventory())


def upsert_directory_record(*, data_root: Path, role: str, root: Path, path: Path) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise StorageValidationError("Folder path escapes the selected storage root.")
    if not resolved_path.is_dir():
        raise StorageValidationError("Folder does not exist.")
    captured: dict[str, Any] = {}

    def updater(payload: dict[str, Any]) -> dict[str, Any]:
        inventory = _normalize_inventory(payload)
        entries = _directory_chain_for_path(role=role, root=resolved_root, path=resolved_path)
        inventory["directories"] = _replace_directories(inventory["directories"], entries)
        inventory["updated_at"] = _timestamp()
        captured.update(_public_folder_record(entries[-1]))
        return inventory

    update_json_state(data_root, INVENTORY_FILE, updater, _empty_inventory())
    return captured


def resolve_file_record(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    entity_id: str,
) -> dict[str, Any] | None:
    value = str(entity_id or "").strip()
    if not value:
        return None
    inventory = ensure_inventory(data_root, uploaded_root=uploaded_root, generated_root=generated_root)
    item = _find_active_by_file_id(inventory["files"], value)
    if item is not None:
        return _public_record(item)
    reference = parse_file_reference(value)
    if reference is None:
        return None
    role, relative_path = reference
    root = _root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root)
    path = (root / relative_path).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return upsert_file_record(data_root=data_root, role=role, root=root, path=path)


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


def _move_inventory_record(*, data_root: Path, role: str, root: Path, old_relative_path: str, new_path: Path) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved_path = new_path.resolve()
    if resolved_root not in resolved_path.parents or not resolved_path.is_file():
        raise StorageValidationError("File does not exist.")
    captured: dict[str, Any] = {}

    def updater(payload: dict[str, Any]) -> dict[str, Any]:
        inventory = _normalize_inventory(payload)
        existing = _find_active_by_path(inventory["files"], role=role, relative_path=old_relative_path)
        if existing is None:
            existing = _find_active_by_path(inventory["files"], role=role, relative_path=resolved_path.relative_to(resolved_root).as_posix())
        now = _timestamp()
        entry = _entry_for_path(
            role=role,
            root=resolved_root,
            path=resolved_path,
            file_id=_existing_file_id(existing),
            sha256=_preserved_hash(existing=existing, path=resolved_path),
            created_at=str(existing.get("created_at") or now) if existing else now,
            status="active",
        )
        inventory["files"] = _replace_entry(inventory["files"], entry, remove_paths={(role, old_relative_path)})
        inventory["directories"] = _replace_directories(
            inventory["directories"],
            _directory_chain_for_path(role=role, root=resolved_root, path=resolved_path.parent),
        )
        inventory["updated_at"] = now
        captured.update(_public_record(entry))
        return inventory

    update_json_state(data_root, INVENTORY_FILE, updater, _empty_inventory())
    return captured


def _sync_inventory_payload(inventory: dict[str, Any], *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    existing_by_path = {
        _path_key(str(item.get("role") or ""), str(item.get("relative_path") or "")): item
        for item in inventory["files"]
        if item.get("status") == "active"
    }
    now = _timestamp()
    discovered_files: list[dict[str, Any]] = []
    discovered_file_keys: set[str] = set()
    discovered_directories: list[dict[str, Any]] = []
    for role, root in _role_roots(uploaded_root=uploaded_root, generated_root=generated_root):
        root.mkdir(parents=True, exist_ok=True)
        resolved_root = root.resolve()
        discovered_directories.append(_directory_entry_for_path(role=role, root=resolved_root, path=resolved_root))
        for path in sorted(resolved_root.rglob("*")):
            try:
                resolved_path = path.resolve()
                if resolved_root not in resolved_path.parents:
                    continue
                is_directory = path.is_dir()
                is_file = path.is_file()
            except OSError:
                continue
            if is_directory:
                try:
                    discovered_directories.append(_directory_entry_for_path(role=role, root=resolved_root, path=resolved_path))
                except OSError:
                    continue
                continue
            if not is_file or _is_temporary_storage_file(path):
                continue
            relative_path = resolved_path.relative_to(resolved_root).as_posix()
            key = _path_key(role, relative_path)
            discovered_file_keys.add(key)
            existing = existing_by_path.get(key)
            try:
                discovered_files.append(
                    _entry_for_path(
                        role=role,
                        root=resolved_root,
                        path=resolved_path,
                        file_id=_existing_file_id(existing),
                        sha256=_preserved_hash(existing=existing, path=resolved_path),
                        created_at=str(existing.get("created_at") or now) if existing else now,
                        status="active",
                    )
                )
            except OSError:
                discovered_file_keys.discard(key)
    tombstones = [
        _deleted_entry(item, now=now)
        for item in inventory["files"]
        if item.get("status") == "active"
        and _path_key(str(item.get("role") or ""), str(item.get("relative_path") or "")) not in discovered_file_keys
    ]
    inactive_files = [item for item in inventory["files"] if item.get("status") != "active"]
    inventory["files"] = _dedupe_by_file_id([*discovered_files, *tombstones, *inactive_files])
    inventory["directories"] = _dedupe_directories(discovered_directories)
    inventory["updated_at"] = now
    return inventory


def _refresh_inventory_payload(inventory: dict[str, Any], *, uploaded_root: Path, generated_root: Path) -> dict[str, Any]:
    now = _timestamp()
    changed = False
    refreshed_files: list[dict[str, Any]] = []
    for item in inventory["files"]:
        if item.get("status") != "active":
            refreshed_files.append(item)
            continue
        role = str(item.get("role") or "")
        relative_path = str(item.get("relative_path") or "")
        root = _root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root)
        path = (root / relative_path).resolve()
        try:
            file_exists = path.is_file()
        except OSError:
            file_exists = False
        if root not in path.parents or not file_exists or _is_temporary_storage_file(path):
            refreshed_files.append(_deleted_entry(item, now=now))
            changed = True
            continue
        try:
            refreshed_item = _entry_for_path(
                role=role,
                root=root,
                path=path,
                file_id=_existing_file_id(item),
                sha256=_preserved_hash(existing=item, path=path),
                created_at=str(item.get("created_at") or now),
                status="active",
            )
        except OSError:
            refreshed_files.append(_deleted_entry(item, now=now))
            changed = True
            continue
        changed = changed or refreshed_item != item
        refreshed_files.append(refreshed_item)

    directories = list(inventory["directories"])
    active_directory_keys = {
        _directory_key(str(item.get("role") or ""), str(item.get("relative_path") or ""))
        for item in directories
        if item.get("status") == "active"
    }
    for role, root in _role_roots(uploaded_root=uploaded_root, generated_root=generated_root):
        root.mkdir(parents=True, exist_ok=True)
        root_entry = _directory_entry_for_path(role=role, root=root.resolve(), path=root.resolve())
        if _directory_key(role, "") not in active_directory_keys:
            directories.append(root_entry)
            active_directory_keys.add(_directory_key(role, ""))
            changed = True

    next_directories: list[dict[str, Any]] = []
    discovered_files = refreshed_files
    for item in directories:
        if item.get("status") != "active":
            next_directories.append(item)
            continue
        role = str(item.get("role") or "")
        relative_path = str(item.get("relative_path") or "")
        root = _root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root)
        directory = (root / relative_path).resolve() if relative_path else root
        if directory != root and root not in directory.parents:
            next_directories.append(_deleted_directory_entry(item, now=now))
            changed = True
            continue
        try:
            directory_exists = directory.is_dir()
        except OSError:
            directory_exists = False
        if not directory_exists:
            next_directories.append(_deleted_directory_entry(item, now=now))
            changed = True
            continue
        try:
            current_directory = _directory_entry_for_path(role=role, root=root, path=directory)
        except OSError:
            next_directories.append(_deleted_directory_entry(item, now=now))
            changed = True
            continue
        directory_changed = int(item.get("mtime_ns") or -1) != int(current_directory.get("mtime_ns") or -1)
        next_directories.append(current_directory)
        changed = changed or directory_changed or current_directory != item
        if directory_changed:
            child_files, child_directories = _discover_directory_children(
                role=role,
                root=root,
                directory=directory,
                existing_files=discovered_files,
                now=now,
            )
            discovered_files = _replace_entries_by_path(discovered_files, child_files)
            next_directories.extend(child_directories)
    inventory["files"] = _dedupe_by_file_id(discovered_files)
    inventory["directories"] = _dedupe_directories(next_directories)
    if changed:
        inventory["updated_at"] = now
    return inventory


def _empty_inventory() -> dict[str, Any]:
    return {"schema_version": INVENTORY_SCHEMA_VERSION, "files": [], "directories": [], "updated_at": ""}


def _normalize_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    files = payload.get("files") if isinstance(payload, dict) and isinstance(payload.get("files"), list) else []
    directories = payload.get("directories") if isinstance(payload, dict) and isinstance(payload.get("directories"), list) else []
    normalized_files = [_normalize_entry(item) for item in files if isinstance(item, dict)]
    normalized_directories = [_normalize_directory_entry(item) for item in directories if isinstance(item, dict)]
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "files": _dedupe_by_file_id(normalized_files),
        "directories": _dedupe_directories(normalized_directories),
        "updated_at": str(payload.get("updated_at") or "") if isinstance(payload, dict) else "",
    }


def _normalize_entry(item: dict[str, Any]) -> dict[str, Any]:
    role = str(item.get("role") or "")
    relative_path = str(item.get("relative_path") or "")
    file_id = str(item.get("file_id") or item.get("id") or "")
    if not stable_file_id(file_id):
        file_id = f"file_{uuid4().hex}"
    workspace_relative_path = f"storage/{role}/{relative_path}" if role in FILE_ROLES and relative_path else str(item.get("workspace_relative_path") or "")
    return {
        "id": file_id,
        "file_id": file_id,
        "path_id": f"{role}:{relative_path}" if role in FILE_ROLES and relative_path else "",
        "role": role,
        "name": str(item.get("name") or Path(relative_path).name),
        "relative_path": relative_path,
        "workspace_relative_path": workspace_relative_path,
        "extension": str(item.get("extension") or Path(relative_path).suffix.lower()),
        "size_bytes": int(item.get("size_bytes") or 0),
        "modified_at": str(item.get("modified_at") or ""),
        "content_type": str(item.get("content_type") or "application/octet-stream"),
        "preview_kind": str(item.get("preview_kind") or "file"),
        "sha256": str(item.get("sha256") or ""),
        "status": str(item.get("status") or "active"),
        "created_at": str(item.get("created_at") or ""),
        "updated_at": str(item.get("updated_at") or ""),
        "deleted_at": str(item.get("deleted_at") or ""),
    }


def _normalize_directory_entry(item: dict[str, Any]) -> dict[str, Any]:
    role = str(item.get("role") or "")
    relative_path = str(item.get("relative_path") or "")
    name = str(item.get("name") or Path(relative_path).name or ("Uploaded" if role == "uploaded" else "Generated"))
    workspace_relative_path = f"storage/{role}" + (f"/{relative_path}" if relative_path else "") if role in FILE_ROLES else ""
    try:
        mtime_ns = int(item.get("mtime_ns") or 0)
    except (TypeError, ValueError):
        mtime_ns = 0
    return {
        "id": f"{role}:{relative_path}/",
        "role": role,
        "name": name,
        "relative_path": relative_path,
        "workspace_relative_path": workspace_relative_path,
        "modified_at": str(item.get("modified_at") or ""),
        "mtime_ns": mtime_ns,
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
) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    stat = path.stat()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    stable_id = file_id if file_id and stable_file_id(file_id) else f"file_{uuid4().hex}"
    return {
        "id": stable_id,
        "file_id": stable_id,
        "path_id": f"{role}:{relative}",
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
        "status": status,
        "created_at": created_at,
        "updated_at": _timestamp(),
        "deleted_at": "",
    }


def _directory_entry_for_path(*, role: str, root: Path, path: Path) -> dict[str, Any]:
    relative = "" if path == root else path.relative_to(root).as_posix()
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    return {
        "id": f"{role}:{relative}/",
        "role": role,
        "name": path.name if relative else ("Uploaded" if role == "uploaded" else "Generated"),
        "relative_path": relative,
        "workspace_relative_path": f"storage/{role}" + (f"/{relative}" if relative else ""),
        "modified_at": modified,
        "mtime_ns": stat.st_mtime_ns,
        "status": "active",
        "updated_at": _timestamp(),
        "deleted_at": "",
    }


def _public_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["file_id"],
        "file_id": item["file_id"],
        "path_id": item["path_id"],
        "role": item["role"],
        "name": item["name"],
        "relative_path": item["relative_path"],
        "workspace_relative_path": item["workspace_relative_path"],
        "extension": item["extension"],
        "size_bytes": item["size_bytes"],
        "modified_at": item["modified_at"],
        "content_type": item["content_type"],
        "preview_kind": item["preview_kind"],
        "sha256": item.get("sha256", ""),
    }


def _public_folder_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "role": item["role"],
        "name": item["name"],
        "relative_path": item["relative_path"],
        "workspace_relative_path": item["workspace_relative_path"],
        "modified_at": item["modified_at"],
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


def _preserved_hash(*, existing: dict[str, Any] | None, path: Path) -> str:
    if not existing:
        return ""
    try:
        size_matches = int(existing.get("size_bytes") or -1) == path.stat().st_size
        modified_matches = str(existing.get("modified_at") or "") == datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return ""
    return str(existing.get("sha256") or "") if size_matches and modified_matches else ""


def _role_roots(*, uploaded_root: Path, generated_root: Path) -> tuple[tuple[str, Path], tuple[str, Path]]:
    return (("uploaded", uploaded_root), ("generated", generated_root))


def _root_for_role(*, role: str, uploaded_root: Path, generated_root: Path) -> Path:
    if role == "uploaded":
        return uploaded_root.resolve()
    if role == "generated":
        return generated_root.resolve()
    raise StorageValidationError(f"Unsupported file role `{role}`.")


def _path_key(role: str, relative_path: str) -> str:
    return f"{role}:{relative_path}"


def _directory_key(role: str, relative_path: str) -> str:
    return f"{role}:{relative_path}/"


def _directory_chain_for_path(*, role: str, root: Path, path: Path) -> list[dict[str, Any]]:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise StorageValidationError("Folder path escapes the selected storage root.")
    entries = [_directory_entry_for_path(role=role, root=resolved_root, path=resolved_root)]
    if resolved_path == resolved_root:
        return entries
    current = resolved_root
    for part in resolved_path.relative_to(resolved_root).parts:
        current = current / part
        if current.is_dir():
            entries.append(_directory_entry_for_path(role=role, root=resolved_root, path=current))
    return entries


def _discover_directory_children(
    *,
    role: str,
    root: Path,
    directory: Path,
    existing_files: list[dict[str, Any]],
    now: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing_by_path = {
        _path_key(str(item.get("role") or ""), str(item.get("relative_path") or "")): item
        for item in existing_files
        if item.get("status") == "active"
    }
    child_files: list[dict[str, Any]] = []
    child_directories: list[dict[str, Any]] = []
    try:
        children = sorted(directory.iterdir())
    except OSError:
        return child_files, child_directories
    for child in children:
        try:
            resolved_child = child.resolve()
            if root not in resolved_child.parents:
                continue
            is_directory = child.is_dir()
            is_file = child.is_file()
        except OSError:
            continue
        if is_directory:
            subtree_files, subtree_directories = _scan_directory_subtree(
                role=role,
                root=root,
                directory=resolved_child,
                existing_by_path=existing_by_path,
                now=now,
            )
            child_files.extend(subtree_files)
            child_directories.extend(subtree_directories)
            continue
        if not is_file or _is_temporary_storage_file(child):
            continue
        relative_path = resolved_child.relative_to(root).as_posix()
        existing = existing_by_path.get(_path_key(role, relative_path))
        try:
            child_files.append(
                _entry_for_path(
                    role=role,
                    root=root,
                    path=resolved_child,
                    file_id=_existing_file_id(existing),
                    sha256=_preserved_hash(existing=existing, path=resolved_child),
                    created_at=str(existing.get("created_at") or now) if existing else now,
                    status="active",
                )
            )
        except OSError:
            continue
    return child_files, child_directories


def _scan_directory_subtree(
    *,
    role: str,
    root: Path,
    directory: Path,
    existing_by_path: dict[str, dict[str, Any]],
    now: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files: list[dict[str, Any]] = []
    try:
        directories = [_directory_entry_for_path(role=role, root=root, path=directory)]
        paths = sorted(directory.rglob("*"))
    except OSError:
        return files, []
    for path in paths:
        try:
            resolved_path = path.resolve()
            if root not in resolved_path.parents:
                continue
            is_directory = path.is_dir()
            is_file = path.is_file()
        except OSError:
            continue
        if is_directory:
            try:
                directories.append(_directory_entry_for_path(role=role, root=root, path=resolved_path))
            except OSError:
                continue
            continue
        if not is_file or _is_temporary_storage_file(path):
            continue
        relative_path = resolved_path.relative_to(root).as_posix()
        existing = existing_by_path.get(_path_key(role, relative_path))
        try:
            files.append(
                _entry_for_path(
                    role=role,
                    root=root,
                    path=resolved_path,
                    file_id=_existing_file_id(existing),
                    sha256=_preserved_hash(existing=existing, path=resolved_path),
                    created_at=str(existing.get("created_at") or now) if existing else now,
                    status="active",
                )
            )
        except OSError:
            continue
    return files, directories


def _find_active_by_path(files: list[dict[str, Any]], *, role: str, relative_path: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in files
            if item.get("status") == "active"
            and item.get("role") == role
            and item.get("relative_path") == relative_path
        ),
        None,
    )


def _find_active_by_file_id(files: list[dict[str, Any]], file_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in files
            if item.get("status") == "active"
            and (item.get("file_id") == file_id or item.get("id") == file_id)
        ),
        None,
    )


def _replace_entry(files: list[dict[str, Any]], entry: dict[str, Any], remove_paths: set[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    remove_paths = remove_paths or set()
    next_files = []
    for item in files:
        same_id = item.get("file_id") == entry["file_id"] or item.get("id") == entry["file_id"]
        same_path = (item.get("role"), item.get("relative_path")) in remove_paths
        if same_id or same_path:
            continue
        next_files.append(item)
    next_files.append(entry)
    return _dedupe_by_file_id(next_files)


def _replace_entries_by_path(files: list[dict[str, Any]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replacement_keys = {
        _path_key(str(item.get("role") or ""), str(item.get("relative_path") or ""))
        for item in entries
    }
    next_files = [
        item
        for item in files
        if _path_key(str(item.get("role") or ""), str(item.get("relative_path") or "")) not in replacement_keys
    ]
    next_files.extend(entries)
    return _dedupe_by_file_id(next_files)


def _replace_directories(directories: list[dict[str, Any]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replacement_keys = {
        _directory_key(str(item.get("role") or ""), str(item.get("relative_path") or ""))
        for item in entries
    }
    next_directories = [
        item
        for item in directories
        if _directory_key(str(item.get("role") or ""), str(item.get("relative_path") or "")) not in replacement_keys
    ]
    next_directories.extend(entries)
    return _dedupe_directories(next_directories)


def _dedupe_by_file_id(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in files:
        entry = _normalize_entry(item)
        file_id = entry["file_id"]
        if file_id in seen:
            continue
        normalized.append(entry)
        seen.add(file_id)
    return normalized


def _dedupe_directories(directories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in directories:
        entry = _normalize_directory_entry(item)
        key = _directory_key(entry["role"], entry["relative_path"])
        if key in seen:
            continue
        normalized.append(entry)
        seen.add(key)
    return normalized


def _is_system_upload_folder(*, role: str, relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return role == "uploaded" and len(parts) == 1 and bool(UPLOAD_BUCKET_PATTERN.fullmatch(parts[0]))


def _is_temporary_storage_file(path: Path) -> bool:
    name = path.name
    return name.startswith(STORAGE_TEMP_PREFIX) and name.endswith(".tmp")


def _folders_from_inventory(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    folders = [
        _public_folder_record(item)
        for item in inventory["directories"]
        if item.get("status") == "active" and str(item.get("relative_path") or "")
    ]
    folders = [
        item
        for item in folders
        if not _is_system_upload_folder(role=item["role"], relative_path=item["relative_path"])
    ]
    folders.sort(key=lambda item: (item["role"], item["relative_path"].casefold()))
    return folders


def _filter_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    role: str,
    kind: str,
    folder_path: str | None = None,
    file_ids: list[str] | None = None,
    workspace_relative_paths: list[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_query = " ".join(str(query or "").casefold().split())
    file_id_filter = {str(value) for value in file_ids or [] if str(value or "").strip()}
    workspace_path_filter = {str(value) for value in workspace_relative_paths or [] if str(value or "").strip()}
    if file_id_filter or workspace_path_filter:
        records = [
            item
            for item in records
            if item["id"] in file_id_filter
            or item["file_id"] in file_id_filter
            or item["path_id"] in file_id_filter
            or item["workspace_relative_path"] in workspace_path_filter
        ]
    if role != "all":
        records = [item for item in records if item["role"] == role]
    if kind != "all":
        records = [item for item in records if item["preview_kind"] == kind]
    if folder_path is not None and role != "all" and not normalized_query:
        normalized_folder_path = _normalize_relative_folder_path(folder_path)
        records = [item for item in records if _visible_file_parent_path(item) == normalized_folder_path]
    if normalized_query:
        records = [
            item
            for item in records
            if normalized_query in f"{item['name']} {item['workspace_relative_path']} {item['content_type']}".casefold()
        ]
    return records


def _normalize_relative_folder_path(value: str | None) -> str:
    return Path(str(value or "").strip().strip("/")).as_posix() if str(value or "").strip().strip("/") else ""


def _visible_file_parent_path(record: dict[str, Any]) -> str:
    role = str(record.get("role") or "")
    parts = Path(str(record.get("relative_path") or "")).parts
    if role == "uploaded" and len(parts) == 2 and UPLOAD_BUCKET_PATTERN.fullmatch(parts[0]):
        return ""
    if len(parts) <= 1:
        return ""
    return Path(*parts[:-1]).as_posix()


def _sort_records(records: list[dict[str, Any]], *, sort_by: str, sort_direction: str) -> list[dict[str, Any]]:
    field = sort_by if sort_by in CATALOG_SORT_FIELDS else "modified_at"
    reverse = sort_direction.lower() != "asc"
    records = sorted(records, key=lambda item: (item["role"], item["relative_path"].casefold()))
    return sorted(records, key=lambda item: item.get(field) or "", reverse=reverse)


def _timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()
