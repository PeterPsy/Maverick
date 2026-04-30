"""Workspace storage inventory helpers for the Gallery app."""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime
import mimetypes
from pathlib import Path
import re

from errors import GalleryValidationError


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


def safe_folder_relative_path(raw_path: object) -> Path:
    value = str(raw_path or "").strip().strip("/")
    if not value:
        return Path()
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise GalleryValidationError("folder path must stay inside the selected storage root.")
    return relative



def reference_from_payload(*, role: str, relative_path: str, workspace_relative_path: str) -> tuple[str, str]:
    normalized_role = str(role or "").strip()
    normalized_relative = str(relative_path or "").strip()
    workspace_relative = str(workspace_relative_path or "").strip()
    if normalized_role and normalized_relative:
        return normalized_role, normalized_relative
    if not workspace_relative:
        raise GalleryValidationError("role and relative_path, or workspace_relative_path, are required.")
    parts = Path(workspace_relative).parts
    if len(parts) < 3 or parts[0] != "storage" or parts[1] not in FILE_ROLES:
        raise GalleryValidationError("workspace_relative_path must start with storage/uploaded/ or storage/generated/.")
    return parts[1], Path(*parts[2:]).as_posix()



def safe_file_name(raw_name: str) -> str:
    value = " ".join(str(raw_name or "").strip().split())
    if not value or value in {".", ".."}:
        raise GalleryValidationError("new_name is required.")
    if "/" in value or "\\" in value or "\x00" in value:
        raise GalleryValidationError("new_name must be a file name, not a path.")
    return value



def safe_folder_name(raw_name: object) -> str:
    value = safe_file_name(str(raw_name or ""))
    if "." == value or value.startswith("."):
        raise GalleryValidationError("folder_name must be a visible folder name.")
    return value



def resolve_storage_file(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path) -> Path:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    candidate = (root / safe_relative_path(relative_path)).resolve()
    if candidate == root or root not in candidate.parents:
        raise GalleryValidationError("File path escapes the selected storage root.")
    if not candidate.is_file():
        raise GalleryValidationError("File does not exist.")
    return candidate



def resolve_storage_folder(*, role: str, relative_path: object, uploaded_root: Path, generated_root: Path, must_exist: bool = True) -> Path:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    relative = safe_folder_relative_path(relative_path)
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise GalleryValidationError("Folder path escapes the selected storage root.")
    if must_exist and not candidate.is_dir():
        raise GalleryValidationError("Folder does not exist.")
    return candidate



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



def file_record(*, role: str, root: Path, path: Path) -> dict:
    relative = path.relative_to(root).as_posix()
    workspace_relative = f"storage/{role}/{relative}"
    stat = path.stat()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
    return {
        "id": f"{role}:{relative}",
        "role": role,
        "name": path.name,
        "relative_path": relative,
        "workspace_relative_path": workspace_relative,
        "extension": path.suffix.lower(),
        "size_bytes": stat.st_size,
        "modified_at": modified,
        "content_type": content_type,
        "preview_kind": preview_kind(content_type, path.suffix),
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



def list_files(*, uploaded_root: Path, generated_root: Path) -> list[dict]:
    records: list[dict] = []
    for role, root in (("uploaded", uploaded_root), ("generated", generated_root)):
        root.mkdir(parents=True, exist_ok=True)
        resolved_root = root.resolve()
        for path in sorted(resolved_root.rglob("*")):
            if not path.is_file():
                continue
            resolved_path = path.resolve()
            if resolved_root not in resolved_path.parents:
                continue
            records.append(file_record(role=role, root=resolved_root, path=resolved_path))
    records.sort(key=lambda item: (item["role"], item["relative_path"].casefold()))
    records.sort(key=lambda item: item["modified_at"], reverse=True)
    return records



def list_folders(*, uploaded_root: Path, generated_root: Path) -> list[dict]:
    records: list[dict] = []
    for role, root in (("uploaded", uploaded_root), ("generated", generated_root)):
        root.mkdir(parents=True, exist_ok=True)
        resolved_root = root.resolve()
        for path in sorted(resolved_root.rglob("*")):
            if not path.is_dir():
                continue
            resolved_path = path.resolve()
            if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
                continue
            relative_path = resolved_path.relative_to(resolved_root).as_posix()
            if is_system_upload_folder(role=role, relative_path=relative_path):
                continue
            records.append(folder_record(role=role, root=resolved_root, path=resolved_path))
    records.sort(key=lambda item: (item["role"], item["relative_path"].casefold()))
    return records



def read_file_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path, max_bytes: int) -> dict:
    if max_bytes <= 0 or max_bytes > MAX_READ_BYTES:
        raise GalleryValidationError(f"max_bytes must be between 1 and {MAX_READ_BYTES}.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    if path.stat().st_size > max_bytes:
        raise GalleryValidationError("File is too large to read through Gallery preview.")
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = file_record(role=role, root=root, path=path.resolve())
    return {
        "file": record,
        "content_base64": b64encode(path.read_bytes()).decode("ascii"),
    }



def write_file_payload(
    *,
    role: str,
    relative_path: str,
    content: object,
    content_base64: object,
    mode: object,
    uploaded_root: Path,
    generated_root: Path,
) -> dict:
    payload = _write_content_bytes(content=content, content_base64=content_base64)
    write_mode = str(mode or "overwrite").strip().lower()
    if write_mode not in {"create", "overwrite", "upsert"}:
        raise GalleryValidationError("mode must be create, overwrite, or upsert.")
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    target = (root / safe_relative_path(relative_path)).resolve()
    if target == root or root not in target.parents:
        raise GalleryValidationError("File path escapes the selected storage root.")
    if target.exists() and not target.is_file():
        raise GalleryValidationError("Target path is not a file.")
    if write_mode == "create" and target.exists():
        raise GalleryValidationError("File already exists.")
    if write_mode == "overwrite" and not target.exists():
        raise GalleryValidationError("File does not exist.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {"file": file_record(role=role, root=root, path=target), "bytes_written": len(payload)}
