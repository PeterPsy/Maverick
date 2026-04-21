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
VIEW_FILTER_ROLES = {"all", *FILE_ROLES}
VIEW_FILTER_KINDS = {"all", "image", "video", "audio", "markdown", "text", "pdf", "document", "presentation", "spreadsheet", "file"}
MAX_VIEW_QUERY_CHARS = 200
MAX_CUSTOM_VIEW_TITLE_CHARS = 140
MAX_CUSTOM_VIEW_FILES = 500
MAX_TEXT_PREVIEW_CACHE_ENTRIES = 200


def state_path(data_root: Path) -> Path:
    return data_root / "state.json"


def text_preview_cache_path(data_root: Path) -> Path:
    return data_root / "preview_cache.json"


def seed_state(data_root: Path) -> dict:
    data_root.mkdir(parents=True, exist_ok=True)
    path = state_path(data_root)
    if not path.exists():
        payload = {"schema_version": SCHEMA_VERSION, "view_mode": "grid", "view_filter": default_view_filter()}
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return load_state(data_root)


def default_view_filter() -> dict:
    return {
        "mode": "search",
        "title": "",
        "query": "",
        "role": "all",
        "kind": "all",
        "file_ids": [],
        "workspace_relative_paths": [],
        "updated_at": "",
    }


def _string_list(raw_value: object, *, max_items: int) -> list[str]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise GalleryValidationError("Custom view file references must be a list.")
    values: list[str] = []
    seen: set[str] = set()
    for item in raw_value:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
        if len(values) > max_items:
            raise GalleryValidationError(f"Custom views can include at most {max_items} files.")
    return values


def _normalize_file_id(file_id: str) -> str:
    role, _, relative_path = file_id.partition(":")
    if role not in FILE_ROLES or not relative_path:
        raise GalleryValidationError("Custom view file ids must use uploaded:<path> or generated:<path>.")
    return f"{role}:{safe_relative_path(relative_path).as_posix()}"


def _normalize_workspace_relative_path(workspace_relative_path: str) -> str:
    role, relative_path = reference_from_payload(role="", relative_path="", workspace_relative_path=workspace_relative_path)
    return f"storage/{role}/{relative_path}"


def _normalize_custom_files(raw_file_ids: object, raw_workspace_relative_paths: object, raw_files: object = None) -> tuple[list[str], list[str]]:
    file_ids = _string_list(raw_file_ids, max_items=MAX_CUSTOM_VIEW_FILES)
    workspace_paths = _string_list(raw_workspace_relative_paths, max_items=MAX_CUSTOM_VIEW_FILES)
    if raw_files is not None:
        if not isinstance(raw_files, list):
            raise GalleryValidationError("Custom view files must be a list.")
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            if item.get("id"):
                file_ids.append(str(item["id"]))
            if item.get("workspace_relative_path"):
                workspace_paths.append(str(item["workspace_relative_path"]))
    normalized_ids: list[str] = []
    normalized_paths: list[str] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for file_id in file_ids:
        normalized = _normalize_file_id(file_id)
        if normalized not in seen_ids:
            normalized_ids.append(normalized)
            seen_ids.add(normalized)
    for workspace_path in workspace_paths:
        normalized = _normalize_workspace_relative_path(workspace_path)
        if normalized not in seen_paths:
            normalized_paths.append(normalized)
            seen_paths.add(normalized)
    if len(normalized_ids) + len(normalized_paths) > MAX_CUSTOM_VIEW_FILES:
        raise GalleryValidationError(f"Custom views can include at most {MAX_CUSTOM_VIEW_FILES} files.")
    return normalized_ids, normalized_paths


def normalize_view_filter(raw_filter: object) -> dict:
    if not isinstance(raw_filter, dict):
        return default_view_filter()
    mode = str(raw_filter.get("mode") or "search").strip()
    if mode not in {"search", "custom"}:
        raise GalleryValidationError(f"Unsupported view filter mode `{mode}`.")
    title = " ".join(str(raw_filter.get("title") or "").split())[:MAX_CUSTOM_VIEW_TITLE_CHARS]
    query = " ".join(str(raw_filter.get("query") or "").split())[:MAX_VIEW_QUERY_CHARS]
    role = str(raw_filter.get("role") or "all").strip()
    kind = str(raw_filter.get("kind") or "all").strip()
    if role not in VIEW_FILTER_ROLES:
        raise GalleryValidationError(f"Unsupported view filter role `{role}`.")
    if kind not in VIEW_FILTER_KINDS:
        raise GalleryValidationError(f"Unsupported view filter kind `{kind}`.")
    file_ids, workspace_relative_paths = _normalize_custom_files(
        raw_filter.get("file_ids"),
        raw_filter.get("workspace_relative_paths"),
    )
    updated_at = str(raw_filter.get("updated_at") or "").strip()
    return {
        "mode": mode,
        "title": title,
        "query": query,
        "role": role,
        "kind": kind,
        "file_ids": file_ids,
        "workspace_relative_paths": workspace_relative_paths,
        "updated_at": updated_at,
    }


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
    payload["view_filter"] = normalize_view_filter(payload.get("view_filter"))
    return payload


def write_state(data_root: Path, payload: dict) -> dict:
    data_root.mkdir(parents=True, exist_ok=True)
    normalized = dict(payload)
    normalized["schema_version"] = SCHEMA_VERSION
    normalized.setdefault("view_mode", "grid")
    normalized["view_filter"] = normalize_view_filter(normalized.get("view_filter"))
    state_path(data_root).write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def set_view_filter_payload(*, data_root: Path, query: object = None, role: object = None, kind: object = None, preserve_custom: bool = False) -> dict:
    state = load_state(data_root)
    current = normalize_view_filter(state.get("view_filter"))
    next_filter = {
        "mode": current["mode"] if preserve_custom else "search",
        "title": current["title"] if preserve_custom else "",
        "query": current["query"] if query is None else query,
        "role": current["role"] if role is None else role,
        "kind": current["kind"] if kind is None else kind,
        "file_ids": current["file_ids"] if preserve_custom else [],
        "workspace_relative_paths": current["workspace_relative_paths"] if preserve_custom else [],
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    state["view_filter"] = normalize_view_filter(next_filter)
    return {"state": write_state(data_root, state)}


def set_custom_view_payload(*, data_root: Path, title: object = None, file_ids: object = None, workspace_relative_paths: object = None, files: object = None, query: object = None, role: object = None, kind: object = None) -> dict:
    normalized_ids, normalized_paths = _normalize_custom_files(file_ids, workspace_relative_paths, files)
    state = load_state(data_root)
    state["view_filter"] = normalize_view_filter(
        {
            "mode": "custom",
            "title": title or "Custom file view",
            "query": "" if query is None else query,
            "role": "all" if role is None else role,
            "kind": "all" if kind is None else kind,
            "file_ids": normalized_ids,
            "workspace_relative_paths": normalized_paths,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
    )
    return {"state": write_state(data_root, state)}


def clear_custom_view_payload(*, data_root: Path) -> dict:
    state = load_state(data_root)
    state["view_filter"] = default_view_filter() | {"updated_at": datetime.now(tz=UTC).isoformat()}
    return {"state": write_state(data_root, state)}


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


def preview_text_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path, data_root: Path, max_chars: int) -> dict:
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
    cache_key = _text_preview_cache_key(record, max_chars)
    cache = _load_text_preview_cache(data_root)
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        return {"file": record, "preview_text": cached, "cache_hit": True}
    preview_text = extract_text_preview(path, record["preview_kind"], max_chars)
    cache[cache_key] = preview_text
    _write_text_preview_cache(data_root, cache)
    return {"file": record, "preview_text": preview_text, "cache_hit": False}


def file_info_payload(*, role: str, relative_path: str, uploaded_root: Path, generated_root: Path) -> dict:
    path = resolve_storage_file(
        role=role,
        relative_path=relative_path,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    return {"file": file_record(role=role, root=root, path=path.resolve())}


def _load_text_preview_cache(data_root: Path) -> dict:
    path = text_preview_cache_path(data_root)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_text_preview_cache(data_root: Path, cache: dict) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    entries = list(cache.items())[-MAX_TEXT_PREVIEW_CACHE_ENTRIES:]
    text_preview_cache_path(data_root).write_text(json.dumps(dict(entries), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text_preview_cache_key(record: dict, max_chars: int) -> str:
    return "|".join(
        [
            record["id"],
            record["modified_at"],
            str(record["size_bytes"]),
            record["preview_kind"],
            str(max_chars),
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
