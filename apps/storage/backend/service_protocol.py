"""Storage action arguments and event declarations shared by read/write handlers."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from errors import StorageValidationError

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
    "upload_local_file": "files",
    "local_upload_session.chunk": "files",
    "write_file": "files",
    "file.content.write": "files",
    "image.compose_pair": "files",
    "image.compose_side_by_side": "files",
    "file.cache_policy.approve": "files",
    "file.cache_policy.revoke": "files",
    "drive_connections.start_oauth": "drive-connections",
    "drive_connections.complete_oauth": "drive-connections",
    "drive_connections.disconnect": "drive-connections",
    "drive_sync": ["files", "drive-connections"],
    "file.reconcile": "files",
    "drive_index": "files",
    "drive_mark_indexed": "files",
    "drive_write": "files",
    "drive_upload_session.chunk": "files",
    "drive_rename": "files",
    "drive_move": "files",
    "drive_trash": "files",
}

DRIVE_SECRET_ACTIONS = {
    "drive_list_roots",
    "drive_list_children",
    "drive_sync",
    "file.reconcile",
    "drive_search",
    "drive_read",
    "drive_preview",
    "drive_export",
    "file.localize",
    "file.localize_status",
    "file.localize_retry",
    "file.localize_cancel",
    "file.local_path.resolve",
    "drive_index",
    "drive_mark_indexed",
    "drive_write",
    "drive_upload_session.start",
    "drive_upload_session.status",
    "drive_upload_session.chunk",
    "drive_upload_session.cancel",
    "drive_rename",
    "drive_move",
    "drive_trash",
}

DRIVE_INDEX_MAX_PREVIEW_CHARS = 20_000

def app_events_for_action(action: str) -> list[dict[str, str]]:
    resource = DATA_CHANGED_RESOURCES.get(action)
    if resource is None:
        return []
    resources = resource if isinstance(resource, list) else [resource]
    return [{"type": "maverick.app.data-changed", "resource": item} for item in resources]

def app_events_for_result(action: str, result: dict[str, Any]) -> list[dict[str, str]]:
    if action == "local_upload_session.chunk":
        session = result.get("upload_session") if isinstance(result.get("upload_session"), dict) else {}
        completed = str(result.get("status") or "").strip() in {"uploaded", "complete"} or str(session.get("status") or "").strip() == "complete"
        if not completed:
            return []
    return app_events_for_action(action)

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
        raise StorageValidationError(
            f"Unsupported catalog {key} `{value}`.",
            operation="catalog",
            allowed_values={key: sorted(allowed)},
            example={"action": "catalog", key: default, "limit": 20},
        )
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

def _file_id_from_body(body: dict[str, Any]) -> str:
    return str(body.get("file_id") or body.get("id") or body.get("entity_id") or "").strip()
