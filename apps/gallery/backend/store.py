"""Workspace storage inventory helpers for the Gallery app."""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime
import json
import mimetypes
from pathlib import Path

from errors import GalleryValidationError
from text_preview import MAX_TEXT_PREVIEW_CHARS, extract_text_preview


SCHEMA_VERSION = "1"
MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_READ_BYTES = 100 * 1024 * 1024
FILE_ROLES = {"uploaded", "generated"}


def state_path(data_root: Path) -> Path:
    return data_root / "state.json"


def seed_state(data_root: Path) -> dict:
    data_root.mkdir(parents=True, exist_ok=True)
    path = state_path(data_root)
    if not path.exists():
        payload = {"schema_version": SCHEMA_VERSION, "view_mode": "grid"}
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return load_state(data_root)


def load_state(data_root: Path) -> dict:
    seed_root = data_root
    seed_root.mkdir(parents=True, exist_ok=True)
    path = state_path(data_root)
    if not path.exists():
        return seed_state(data_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GalleryValidationError("Gallery state must be a JSON object.")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("view_mode", "grid")
    return payload


def storage_root_for_role(*, role: str, uploaded_root: Path, generated_root: Path) -> Path:
    if role == "uploaded":
        return uploaded_root
    if role == "generated":
        return generated_root
    raise GalleryValidationError(f"Unsupported file role `{role}`.")


def safe_relative_path(raw_path: str) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        raise GalleryValidationError("relative_path is required.")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise GalleryValidationError("relative_path must stay inside the selected storage root.")
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


def resolve_storage_file(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path) -> Path:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    candidate = (root / safe_relative_path(relative_path)).resolve()
    if candidate == root or root not in candidate.parents:
        raise GalleryValidationError("File path escapes the selected storage root.")
    if not candidate.is_file():
        raise GalleryValidationError("File does not exist.")
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
    return sorted(records, key=lambda item: (item["role"], item["relative_path"].casefold()))


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


def preview_text_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path, max_chars: int) -> dict:
    if max_chars <= 0 or max_chars > MAX_TEXT_PREVIEW_CHARS:
        raise GalleryValidationError(f"max_chars must be between 1 and {MAX_TEXT_PREVIEW_CHARS}.")
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = file_record(role=role, root=root, path=path.resolve())
    return {"file": record, "preview_text": extract_text_preview(path, record["preview_kind"], max_chars)}


def file_info_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path) -> dict:
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    return {"file": file_record(role=role, root=root, path=path.resolve())}


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


def delete_file_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path) -> dict:
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = file_record(role=role, root=root, path=path.resolve())
    path.unlink()
    return {"deleted": True, "file": record}
