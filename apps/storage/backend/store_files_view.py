"""Workspace storage inventory helpers for the Storage app."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re

from core.app_sdk.storage import read_json_state, write_json_state
from errors import StorageValidationError
from inventory import stable_file_id
from store_files_paths import reference_from_payload, safe_relative_path


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


def state_path(data_root: Path) -> Path:
    return data_root / "state.json"



def text_preview_cache_path(data_root: Path) -> Path:
    return data_root / "preview_cache.json"



def seed_state(data_root: Path) -> dict:
    data_root.mkdir(parents=True, exist_ok=True)
    path = state_path(data_root)
    if not path.exists():
        payload = {"schema_version": SCHEMA_VERSION, "view_mode": "grid", "view_filter": default_view_filter()}
        write_json_state(data_root, "state.json", payload)
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
        raise StorageValidationError("Custom view file references must be a list.")
    values: list[str] = []
    seen: set[str] = set()
    for item in raw_value:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
        if len(values) > max_items:
            raise StorageValidationError(f"Custom views can include at most {max_items} files.")
    return values



def _normalize_file_id(file_id: str) -> str:
    if stable_file_id(file_id):
        return file_id
    role, _, relative_path = file_id.partition(":")
    if role not in FILE_ROLES or not relative_path:
        raise StorageValidationError("Custom view file ids must use stable file_<id>, uploaded:<path>, or generated:<path>.")
    return f"{role}:{safe_relative_path(relative_path).as_posix()}"



def _normalize_workspace_relative_path(workspace_relative_path: str) -> str:
    role, relative_path = reference_from_payload(role="", relative_path="", workspace_relative_path=workspace_relative_path)
    return f"storage/{role}/{relative_path}"



def _normalize_custom_files(raw_file_ids: object, raw_workspace_relative_paths: object, raw_files: object = None) -> tuple[list[str], list[str]]:
    file_ids = _string_list(raw_file_ids, max_items=MAX_CUSTOM_VIEW_FILES)
    workspace_paths = _string_list(raw_workspace_relative_paths, max_items=MAX_CUSTOM_VIEW_FILES)
    if raw_files is not None:
        if not isinstance(raw_files, list):
            raise StorageValidationError("Custom view files must be a list.")
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
        raise StorageValidationError(f"Custom views can include at most {MAX_CUSTOM_VIEW_FILES} files.")
    return normalized_ids, normalized_paths



def normalize_view_filter(raw_filter: object) -> dict:
    if not isinstance(raw_filter, dict):
        return default_view_filter()
    mode = str(raw_filter.get("mode") or "search").strip()
    if mode not in {"search", "custom"}:
        raise StorageValidationError(f"Unsupported view filter mode `{mode}`.")
    title = " ".join(str(raw_filter.get("title") or "").split())[:MAX_CUSTOM_VIEW_TITLE_CHARS]
    query = " ".join(str(raw_filter.get("query") or "").split())[:MAX_VIEW_QUERY_CHARS]
    role = str(raw_filter.get("role") or "all").strip()
    kind = str(raw_filter.get("kind") or "all").strip()
    if role not in VIEW_FILTER_ROLES:
        raise StorageValidationError(f"Unsupported view filter role `{role}`.")
    if kind not in VIEW_FILTER_KINDS:
        raise StorageValidationError(f"Unsupported view filter kind `{kind}`.")
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
    payload = read_json_state(data_root, "state.json")
    if not isinstance(payload, dict):
        raise StorageValidationError("Storage state must be a JSON object.")
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
    write_json_state(data_root, "state.json", normalized)
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
