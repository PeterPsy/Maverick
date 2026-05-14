"""Storage app service layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import StorageValidationError
from reference_entities import (
    REFERENCE_MANIFEST,
    reference_resolve_payload,
    reference_search_payload,
    reference_summarize_payload,
)
from render_preview import rendered_preview_payload, rendered_thumbnail_payload
from store import (
    MAX_PREVIEW_BYTES,
    MAX_READ_BYTES,
    catalog_files_payload,
    create_folder_payload,
    delete_folder_payload,
    delete_file_payload,
    file_info_payload,
    load_state,
    move_file_payload,
    move_folder_payload,
    move_items_payload,
    preview_table_payload,
    preview_text_payload,
    read_file_payload,
    read_folder_payload,
    reference_from_payload,
    rename_file_payload,
    seed_state,
    clear_custom_view_payload,
    set_custom_view_payload,
    set_view_filter_payload,
    update_markdown_file_payload,
    upload_file_payload,
    write_file_payload,
)

CATALOG_ROLES = {"all", "uploaded", "generated"}
CATALOG_KINDS = {
    "all",
    "audio",
    "document",
    "file",
    "image",
    "markdown",
    "pdf",
    "presentation",
    "spreadsheet",
    "text",
    "video",
}

DATA_CHANGED_RESOURCES = {
    "set_view_filter": "view-state",
    "set_custom_view": "view-state",
    "clear_custom_view": "view-state",
    "rename_file": "files",
    "delete_file": "files",
    "delete_folder": "files",
    "create_folder": "files",
    "move_file": "files",
    "move_folder": "files",
    "move_items": "files",
    "update_markdown_file": "files",
    "upload_file": "files",
    "write_file": "files",
    "file.content.write": "files",
}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    resource = DATA_CHANGED_RESOURCES.get(action)
    if resource is None:
        return []
    return [{"type": "maverick.app.data-changed", "resource": resource}]


def _optional_int(body: dict[str, Any], key: str) -> int | None:
    raw_value = body.get(key)
    if key not in body or raw_value is None or raw_value == "":
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as error:
        raise StorageValidationError(f"{key} must be an integer.") from error


def _optional_nonnegative_int(body: dict[str, Any], key: str) -> int | None:
    value = _optional_int(body, key)
    if value is not None and value < 0:
        raise StorageValidationError(f"{key} must not be negative.")
    return value


def _optional_positive_int(body: dict[str, Any], key: str, *, maximum: int | None = None) -> int | None:
    value = _optional_int(body, key)
    if value is None:
        return None
    if value <= 0:
        raise StorageValidationError(f"{key} must be positive.")
    if maximum is not None and value > maximum:
        raise StorageValidationError(f"{key} must be at most {maximum}.")
    return value


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _catalog_filter_value(body: dict[str, Any], key: str, allowed: set[str], default: str) -> str:
    value = str(body.get(key) or default).strip()
    if value not in allowed:
        raise StorageValidationError(f"Unsupported catalog {key} `{value}`.")
    return value


def _catalog_folder_path(body: dict[str, Any]) -> str | None:
    if "folder_path" not in body or body.get("folder_path") is None:
        return None
    value = str(body.get("folder_path") or "").strip().strip("/")
    if not value:
        return ""
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageValidationError("folder_path must stay inside the selected storage root.")
    return relative.as_posix()


def _optional_string_list(body: dict[str, Any], key: str, *, maximum: int = 500) -> list[str] | None:
    if key not in body or body.get(key) is None:
        return None
    raw_value = body.get(key)
    if not isinstance(raw_value, list):
        raise StorageValidationError(f"{key} must be an array.")
    values = [str(item).strip() for item in raw_value if str(item or "").strip()]
    if len(values) > maximum:
        raise StorageValidationError(f"{key} must contain at most {maximum} items.")
    return values


def handle_action(data_root: Path, uploaded_root: Path, generated_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "catalog")
    if action in {"catalog", "file.catalog.list"}:
        catalog = catalog_files_payload(
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            sync=_bool_value(body.get("sync")),
            query=str(body.get("query") or ""),
            role=_catalog_filter_value(body, "role", CATALOG_ROLES, "all"),
            kind=_catalog_filter_value(body, "kind", CATALOG_KINDS, "all"),
            offset=_optional_nonnegative_int(body, "offset") or 0,
            limit=_optional_positive_int(body, "limit", maximum=2000),
            sort_by=str(body.get("sort_by") or "modified_at"),
            sort_direction=str(body.get("sort_direction") or "desc"),
            folder_path=_catalog_folder_path(body),
            file_ids=_optional_string_list(body, "file_ids"),
            workspace_relative_paths=_optional_string_list(body, "workspace_relative_paths"),
        )
        return 200, {
            "state": load_state(data_root),
            "files": catalog["files"],
            "folders": catalog["folders"],
            "pagination": catalog["pagination"],
            "inventory": catalog["inventory"],
            "available_kinds": catalog["available_kinds"],
        }
    if action == "view_filter":
        return 200, {"state": load_state(data_root)}
    if action == "set_view_filter":
        return 200, set_view_filter_payload(
            data_root=data_root,
            query=body.get("query") if "query" in body else None,
            role=body.get("role") if "role" in body else None,
            kind=body.get("kind") if "kind" in body else None,
            preserve_custom=bool(body.get("preserve_custom")),
        )
    if action == "set_custom_view":
        return 200, set_custom_view_payload(
            data_root=data_root,
            title=body.get("title"),
            file_ids=body.get("file_ids"),
            workspace_relative_paths=body.get("workspace_relative_paths"),
            files=body.get("files"),
            query=body.get("query") if "query" in body else None,
            role=body.get("role") if "role" in body else None,
            kind=body.get("kind") if "kind" in body else None,
        )
    if action == "clear_custom_view":
        return 200, clear_custom_view_payload(data_root=data_root)
    if action in {"read_file", "file.content.read"}:
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        max_bytes = _optional_positive_int(body, "max_bytes", maximum=MAX_READ_BYTES) or MAX_PREVIEW_BYTES
        return 200, read_file_payload(
            role=role,
            relative_path=relative_path,
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            max_bytes=max_bytes,
        )
    if action in {"write_file", "file.content.write"}:
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or "generated"),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, write_file_payload(
            role=role,
            relative_path=relative_path,
            data_root=data_root,
            content=body.get("content"),
            content_base64=body.get("content_base64"),
            mode=body.get("mode"),
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "upload_file":
        return 200, upload_file_payload(
            role=str(body.get("role") or ""),
            folder_relative_path=body.get("folder_relative_path"),
            file_name=body.get("file_name"),
            content_base64=body.get("content_base64"),
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action in {"preview_text", "file.preview.text"}:
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, preview_text_payload(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            data_root=data_root,
            max_chars=_optional_int(body, "max_chars"),
        )
    if action in {"preview_table", "file.preview.table"}:
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, preview_table_payload(
            role=role,
            relative_path=relative_path,
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            max_rows=_optional_int(body, "max_rows"),
            max_columns=_optional_int(body, "max_columns"),
        )
    if action in {"render_preview", "file.preview.render"}:
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        file_payload = file_info_payload(
            role=role,
            relative_path=relative_path,
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        root = uploaded_root.resolve() if role == "uploaded" else generated_root.resolve()
        path = (root / relative_path).resolve()
        if root not in path.parents:
            raise StorageValidationError("File path escapes the selected storage root.")
        return 200, rendered_preview_payload(
            path=path,
            root=root,
            role=role,
            data_root=data_root,
        ) | {"file": file_payload["file"]}
    if action == "render_thumbnail":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        file_payload = file_info_payload(
            role=role,
            relative_path=relative_path,
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        root = uploaded_root.resolve() if role == "uploaded" else generated_root.resolve()
        path = (root / relative_path).resolve()
        if root not in path.parents:
            raise StorageValidationError("File path escapes the selected storage root.")
        return 200, rendered_thumbnail_payload(
            path=path,
            root=root,
            role=role,
            data_root=data_root,
        ) | {"file": file_payload["file"]}
    if action == "file_info":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, file_info_payload(
            role=role,
            relative_path=relative_path,
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "rename_file":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, rename_file_payload(
            role=role,
            relative_path=relative_path,
            new_name=str(body.get("new_name") or ""),
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "update_markdown_file":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, update_markdown_file_payload(
            role=role,
            relative_path=relative_path,
            content=body.get("content"),
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "create_folder":
        role = str(body.get("role") or "")
        return 200, create_folder_payload(
            role=role,
            parent_relative_path=body.get("parent_relative_path"),
            folder_name=body.get("folder_name"),
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action in {"download_folder", "read_folder"}:
        role = str(body.get("role") or "")
        return 200, read_folder_payload(
            role=role,
            relative_path=body.get("relative_path"),
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "move_file":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, move_file_payload(
            role=role,
            relative_path=relative_path,
            target_folder_relative_path=body.get("target_folder_relative_path"),
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "move_folder":
        role = str(body.get("role") or "")
        return 200, move_folder_payload(
            role=role,
            relative_path=body.get("relative_path"),
            target_folder_relative_path=body.get("target_folder_relative_path"),
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "move_items":
        role = str(body.get("role") or "")
        return 200, move_items_payload(
            role=role,
            files=body.get("files"),
            folders=body.get("folders"),
            target_folder_relative_path=body.get("target_folder_relative_path"),
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "delete_file":
        role, relative_path = reference_from_payload(
            role=str(body.get("role") or ""),
            relative_path=str(body.get("relative_path") or ""),
            workspace_relative_path=str(body.get("workspace_relative_path") or ""),
        )
        return 200, delete_file_payload(
            role=role,
            relative_path=relative_path,
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "delete_folder":
        role = str(body.get("role") or "")
        return 200, delete_folder_payload(
            role=role,
            relative_path=body.get("relative_path"),
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
    if action == "health.check":
        seed_state(data_root)
        uploaded_root.mkdir(parents=True, exist_ok=True)
        generated_root.mkdir(parents=True, exist_ok=True)
        return 200, {"status": "ok", "storage_roots": {"uploaded": uploaded_root.is_dir(), "generated": generated_root.is_dir()}}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        return 200, reference_search_payload(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root, body=body)
    if action == "references.resolve":
        return 200, reference_resolve_payload(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root, body=body)
    if action == "references.summarize":
        return 200, reference_summarize_payload(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root, body=body)
    raise StorageValidationError(f"Unknown action `{action}`.")
