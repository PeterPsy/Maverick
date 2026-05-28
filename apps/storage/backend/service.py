"""Storage app service layer."""

from __future__ import annotations

from base64 import b64decode
import binascii
from pathlib import Path
from typing import Any

from errors import StorageValidationError
from drive_connection_store import append_audit, get_connection, now_timestamp, sync_state_for_connection, update_connection_sync_state
from drive_oauth import complete_oauth, disconnect_connection, list_drive_connections, start_oauth
from google_drive_provider import DriveProviderError, GoogleDriveProvider
from inventory import upsert_remote_file_records
from operations_manifest import STORAGE_ACTION_ALIASES, STORAGE_ACTIONS, operations_manifest_payload
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
    file_info_by_id_payload,
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
from storage_provider_model import GOOGLE_DRIVE_PROVIDER, reject_remote_workspace_relative_path
from storage_reference_resolver import StorageReferenceResolver

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
    "drive_connections.start_oauth": "drive-connections",
    "drive_connections.complete_oauth": "drive-connections",
    "drive_connections.disconnect": "drive-connections",
    "drive_list_children": "files",
    "drive_search": "files",
    "drive_sync": ["files", "drive-connections"],
    "drive_index": "files",
    "drive_write": "files",
    "drive_rename": "files",
    "drive_move": "files",
    "drive_trash": "files",
}

DRIVE_SECRET_ACTIONS = {
    "drive_list_roots",
    "drive_list_children",
    "drive_sync",
    "drive_search",
    "drive_read",
    "drive_preview",
    "drive_export",
    "drive_index",
    "drive_write",
    "drive_rename",
    "drive_move",
    "drive_trash",
}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    resource = DATA_CHANGED_RESOURCES.get(action)
    if resource is None:
        return []
    resources = resource if isinstance(resource, list) else [resource]
    return [{"type": "maverick.app.data-changed", "resource": item} for item in resources]


def secret_lookup_for_drive_action(
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    action = STORAGE_ACTION_ALIASES.get(str(body.get("action") or ""), str(body.get("action") or ""))
    if action not in DRIVE_SECRET_ACTIONS:
        return {"requires_secrets": False}
    connection_id = str(body.get("connection_id") or "").strip()
    if not connection_id:
        stable_id = str(body.get("stable_storage_file_id") or body.get("file_id") or body.get("id") or body.get("entity_id") or "").strip()
        if stable_id:
            try:
                record = StorageReferenceResolver(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root).require_file(stable_id)
            except (StorageValidationError, ValueError):
                record = {}
            if record.get("provider") == GOOGLE_DRIVE_PROVIDER:
                connection_id = str(record.get("connection_id") or "").strip()
    if not connection_id:
        return {"requires_secrets": False}
    return {"requires_secrets": True, "resource_type": "drive_connection", "resource_id": connection_id}


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


def handle_action(
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    body: dict[str, Any],
    *,
    allow_platform_secret_writes: bool = False,
    oauth_transport=None,
    drive_transport=None,
) -> tuple[int, dict[str, Any]]:
    requested_action = str(body.get("action") or "catalog")
    action = STORAGE_ACTION_ALIASES.get(requested_action, requested_action)
    reject_remote_workspace_relative_path(
        provider=body.get("provider"),
        workspace_relative_path=body.get("workspace_relative_path"),
        workspace_relative_paths=body.get("workspace_relative_paths"),
    )
    if action == "operations.manifest":
        return 200, operations_manifest_payload()
    if action == "drive_connections.list":
        return 200, list_drive_connections(data_root, body)
    if action == "drive_connections.start_oauth":
        return 200, start_oauth(data_root, body)
    if action == "drive_connections.complete_oauth":
        return 200, complete_oauth(
            data_root,
            body,
            allow_platform_secret_writes=allow_platform_secret_writes,
            transport=oauth_transport,
        )
    if action == "drive_connections.disconnect":
        return 200, disconnect_connection(data_root, body)
    if action == "drive_list_roots":
        provider = _google_drive_provider(data_root, body, transport=drive_transport)
        return 200, provider.list_roots(limit=_optional_positive_int(body, "limit", maximum=2000))
    if action == "drive_list_children":
        provider = _google_drive_provider(data_root, body, transport=drive_transport)
        result = provider.list_children(
            parent_drive_file_id=str(body.get("parent_drive_file_id") or body.get("drive_file_id") or "root"),
            limit=_optional_positive_int(body, "limit", maximum=2000),
        )
        _persist_drive_files(data_root, result)
        return 200, result
    if action == "drive_search":
        provider = _google_drive_provider(data_root, body, transport=drive_transport)
        result = provider.search(
            query=str(body.get("query") or ""),
            parent_drive_file_id=str(body.get("parent_drive_file_id") or ""),
            limit=_optional_positive_int(body, "limit", maximum=2000),
        )
        _persist_drive_files(data_root, result)
        return 200, result
    if action == "drive_sync":
        provider = _google_drive_provider(data_root, body, transport=drive_transport)
        return 200, _sync_drive_changes(
            data_root=data_root,
            provider=provider,
            connection_id=str(body.get("connection_id") or ""),
            limit=_optional_positive_int(body, "limit", maximum=2000),
        )
    if action == "drive_read":
        connection_id, drive_file_id = _drive_locator_from_body(data_root, uploaded_root, generated_root, body)
        provider = _google_drive_provider(data_root, {**body, "connection_id": connection_id}, transport=drive_transport)
        return 200, provider.read(
            drive_file_id=drive_file_id,
            max_bytes=_optional_positive_int(body, "max_bytes", maximum=MAX_READ_BYTES) or MAX_PREVIEW_BYTES,
        )
    if action == "drive_preview":
        connection_id, drive_file_id = _drive_locator_from_body(data_root, uploaded_root, generated_root, body)
        provider = _google_drive_provider(data_root, {**body, "connection_id": connection_id}, transport=drive_transport)
        return 200, provider.preview(
            drive_file_id=drive_file_id,
            max_bytes=_optional_positive_int(body, "max_bytes", maximum=MAX_READ_BYTES) or MAX_PREVIEW_BYTES,
            max_chars=_optional_positive_int(body, "max_chars"),
        )
    if action == "drive_export":
        connection_id, drive_file_id = _drive_locator_from_body(data_root, uploaded_root, generated_root, body)
        provider = _google_drive_provider(data_root, {**body, "connection_id": connection_id}, transport=drive_transport)
        return 200, provider.export(
            drive_file_id=drive_file_id,
            export_mime_type=str(body.get("export_mime_type") or body.get("format") or "readable_text"),
            max_bytes=_optional_positive_int(body, "max_bytes", maximum=MAX_READ_BYTES) or MAX_PREVIEW_BYTES,
        )
    if action == "drive_index":
        connection_id, drive_file_id = _drive_locator_from_body(data_root, uploaded_root, generated_root, body)
        provider = _google_drive_provider(data_root, {**body, "connection_id": connection_id}, transport=drive_transport)
        result = _drive_index_payload(
            data_root=data_root,
            provider=provider,
            connection_id=connection_id,
            drive_file_id=drive_file_id,
            max_bytes=_optional_positive_int(body, "max_bytes", maximum=MAX_READ_BYTES) or MAX_PREVIEW_BYTES,
            max_chars=_optional_positive_int(body, "max_chars"),
        )
        return 200, result
    if action == "drive_write":
        content, content_type = _drive_content_from_body(body)
        if str(body.get("drive_file_id") or body.get("stable_storage_file_id") or body.get("file_id") or body.get("id") or body.get("entity_id") or "").strip():
            connection_id, drive_file_id = _drive_locator_from_body(data_root, uploaded_root, generated_root, body)
            provider = _google_drive_provider(data_root, {**body, "connection_id": connection_id}, transport=drive_transport)
            result = provider.update_content(drive_file_id=drive_file_id, content=content, content_type=content_type)
            _persist_drive_write_result(data_root, result)
            _audit_drive_write(data_root, "drive.file.content_update", connection_id, result)
            return 200, result
        connection_id = str(body.get("connection_id") or "").strip()
        provider = _google_drive_provider(data_root, body, transport=drive_transport)
        result = provider.upload(
            parent_drive_file_id=str(body.get("parent_drive_file_id") or ""),
            file_name=str(body.get("file_name") or ""),
            content=content,
            content_type=content_type,
        )
        _persist_drive_write_result(data_root, result)
        _audit_drive_write(data_root, "drive.file.upload", connection_id, result)
        return 200, result
    if action == "drive_rename":
        connection_id, drive_file_id = _drive_locator_from_body(data_root, uploaded_root, generated_root, body)
        provider = _google_drive_provider(data_root, {**body, "connection_id": connection_id}, transport=drive_transport)
        result = provider.rename(drive_file_id=drive_file_id, new_name=str(body.get("new_name") or ""))
        _persist_drive_write_result(data_root, result)
        _audit_drive_write(data_root, "drive.file.rename", connection_id, result)
        return 200, result
    if action == "drive_move":
        connection_id, drive_file_id = _drive_locator_from_body(data_root, uploaded_root, generated_root, body)
        provider = _google_drive_provider(data_root, {**body, "connection_id": connection_id}, transport=drive_transport)
        result = provider.move(
            drive_file_id=drive_file_id,
            target_parent_drive_file_id=str(body.get("target_parent_drive_file_id") or ""),
        )
        _persist_drive_write_result(data_root, result)
        _audit_drive_write(data_root, "drive.file.move", connection_id, result)
        return 200, result
    if action == "drive_trash":
        _require_delete_confirmation(body)
        connection_id, drive_file_id = _drive_locator_from_body(data_root, uploaded_root, generated_root, body)
        provider = _google_drive_provider(data_root, {**body, "connection_id": connection_id}, transport=drive_transport)
        result = provider.trash(drive_file_id=drive_file_id)
        _persist_drive_write_result(data_root, result)
        _audit_drive_write(data_root, "drive.file.trash", connection_id, result)
        return 200, result
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
        file_id = _file_id_from_body(body)
        if file_id:
            return 200, file_info_by_id_payload(
                file_id=file_id,
                data_root=data_root,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
            )
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
    raise StorageValidationError(
        f"Unknown action `{action}`.",
        operation=action,
        expected_fields=["action"],
        accepted_aliases={
            "write": ["write-file", "write-content"],
            "read_file": ["file.content.read"],
        },
        allowed_values={"action": STORAGE_ACTIONS},
        example={"action": "operations.manifest"},
    )


def _google_drive_provider(data_root: Path, body: dict[str, Any], *, transport=None) -> GoogleDriveProvider:
    connection_id = str(body.get("connection_id") or "").strip()
    if not connection_id:
        raise StorageValidationError("connection_id is required.", operation=str(body.get("action") or "drive"))
    try:
        connection = get_connection(data_root, connection_id)
    except ValueError as error:
        raise StorageValidationError(str(error), operation=str(body.get("action") or "drive")) from error
    app_secrets = body.get("_app_secrets") if isinstance(body.get("_app_secrets"), dict) else {}
    return GoogleDriveProvider(connection=connection, app_secrets=app_secrets, transport=transport, cache_root=data_root / "drive_temp_cache")


def _drive_locator_from_body(data_root: Path, uploaded_root: Path, generated_root: Path, body: dict[str, Any]) -> tuple[str, str]:
    connection_id = str(body.get("connection_id") or "").strip()
    drive_file_id = str(body.get("drive_file_id") or "").strip()
    if connection_id and drive_file_id:
        return connection_id, drive_file_id
    stable_id = str(body.get("stable_storage_file_id") or body.get("file_id") or body.get("id") or body.get("entity_id") or "").strip()
    if not stable_id:
        raise StorageValidationError(
            "connection_id and drive_file_id, or stable_storage_file_id, are required.",
            operation=str(body.get("action") or "drive"),
            expected_fields=["connection_id", "drive_file_id"],
        )
    record = StorageReferenceResolver(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root).require_file(stable_id)
    if record.get("provider") != GOOGLE_DRIVE_PROVIDER:
        raise StorageValidationError("The requested Storage file is not a Google Drive file.", operation=str(body.get("action") or "drive"))
    resolved_connection_id = str(record.get("connection_id") or "").strip()
    remote_locator = record.get("remote_locator") if isinstance(record.get("remote_locator"), dict) else {}
    resolved_drive_file_id = str(record.get("drive_file_id") or remote_locator.get("drive_file_id") or "").strip()
    if not resolved_connection_id or not resolved_drive_file_id:
        raise StorageValidationError("Google Drive Storage reference is missing its remote locator.", operation=str(body.get("action") or "drive"))
    if connection_id and connection_id != resolved_connection_id:
        raise StorageValidationError("connection_id does not match the stable Storage file reference.", operation=str(body.get("action") or "drive"))
    return resolved_connection_id, resolved_drive_file_id


def _persist_drive_files(data_root: Path, result: dict[str, Any]) -> list[dict[str, Any]]:
    files = result.get("files") if isinstance(result.get("files"), list) else []
    return upsert_remote_file_records(data_root=data_root, records=[item for item in files if isinstance(item, dict)])


def _sync_drive_changes(
    *,
    data_root: Path,
    provider: GoogleDriveProvider,
    connection_id: str,
    limit: int | None,
) -> dict[str, Any]:
    current_state = sync_state_for_connection(data_root, connection_id)
    page_token = str(current_state.get("last_processed_page_token") or current_state.get("start_page_token") or "")
    if not page_token:
        try:
            start_page_token = provider.start_page_token()
        except DriveProviderError as error:
            message = _redacted_provider_error(error)
            sync_state = update_connection_sync_state(
                data_root,
                connection_id,
                {"status": "error", "error": message, "last_sync_at": now_timestamp()},
            )
            raise StorageValidationError(message, operation="drive_sync") from error
        sync_state = update_connection_sync_state(
            data_root,
            connection_id,
            {
                "start_page_token": start_page_token,
                "last_processed_page_token": start_page_token,
                "last_sync_at": now_timestamp(),
                "status": "healthy",
                "error": "",
            },
        )
        return {
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": connection_id,
            "sync_mode": "start_page_token",
            "changes_processed": 0,
            "synced_files": 0,
            "removed_files": [],
            "removed_file_count": 0,
            "stale_storage_file_ids": [],
            "memory_staleness": [],
            "sync_state": sync_state,
        }
    update_connection_sync_state(data_root, connection_id, {"status": "syncing", "error": ""})
    try:
        result = provider.list_changes(page_token=page_token, limit=limit)
    except DriveProviderError as error:
        message = _redacted_provider_error(error)
        sync_state = update_connection_sync_state(
            data_root,
            connection_id,
            {"status": "error", "error": message, "last_sync_at": now_timestamp()},
        )
        raise StorageValidationError(message, operation="drive_sync") from error
    changed_files = result.get("files") if isinstance(result.get("files"), list) else []
    removed_files = result.get("removed_files") if isinstance(result.get("removed_files"), list) else []
    records = [item for item in [*changed_files, *removed_files] if isinstance(item, dict)]
    persisted = upsert_remote_file_records(data_root=data_root, records=records)
    sync_state = update_connection_sync_state(
        data_root,
        connection_id,
        {
            "last_processed_page_token": result.get("last_processed_page_token") or page_token,
            "last_sync_at": now_timestamp(),
            "status": "healthy",
            "error": "",
        },
    )
    stale_records = [item for item in persisted if bool(item.get("stale")) or str(item.get("status") or "") != "active"]
    stale_ids = [str(item.get("file_id") or item.get("stable_storage_file_id") or item.get("id")) for item in stale_records]
    return {
        **result,
        "synced_files": len([item for item in persisted if str(item.get("status") or "") == "active"]),
        "removed_file_count": len([item for item in persisted if str(item.get("status") or "") != "active"]),
        "stale_storage_file_ids": stale_ids,
        "memory_staleness": [
            {
                "owning_app_id": "storage",
                "entity_type": "file",
                "entity_id": file_id,
                "reason": "google_drive_change",
            }
            for file_id in stale_ids
        ],
        "sync_state": sync_state,
    }


def _persist_drive_write_result(data_root: Path, result: dict[str, Any]) -> list[dict[str, Any]]:
    file_record = result.get("file") if isinstance(result.get("file"), dict) else None
    if file_record is None:
        return []
    return upsert_remote_file_records(data_root=data_root, records=[file_record])


def _drive_index_payload(
    *,
    data_root: Path,
    provider: GoogleDriveProvider,
    connection_id: str,
    drive_file_id: str,
    max_bytes: int,
    max_chars: int | None,
) -> dict[str, Any]:
    preview = provider.preview(drive_file_id=drive_file_id, max_bytes=max_bytes, max_chars=max_chars)
    file_record = preview.get("file") if isinstance(preview.get("file"), dict) else provider.metadata(drive_file_id=drive_file_id)
    persisted = upsert_remote_file_records(data_root=data_root, records=[file_record])
    public_file = persisted[0] if persisted else file_record
    source_version = str(public_file.get("etag_or_version") or public_file.get("modified_at") or "")
    storage_file_id = str(public_file.get("file_id") or public_file.get("stable_storage_file_id") or public_file.get("id") or "")
    return {
        "status": "ready_for_memory",
        "provider": GOOGLE_DRIVE_PROVIDER,
        "connection_id": connection_id,
        "drive_file_id": drive_file_id,
        "file": public_file,
        "source_version": source_version,
        "preview_text": str(preview.get("preview_text") or ""),
        "bytes_read": int(preview.get("bytes_read") or 0),
        "truncated": bool(preview.get("truncated") or False),
        "cache_hit": bool(preview.get("cache_hit") or False),
        "memory_source": {
            "source_kind": "remote_storage_file",
            "owning_app_id": "storage",
            "entity_type": "file",
            "entity_id": storage_file_id,
            "file_id": storage_file_id,
            "workspace_relative_path": "",
            "metadata": {
                "provider": GOOGLE_DRIVE_PROVIDER,
                "connection_id": connection_id,
                "drive_file_id": drive_file_id,
                "source_version": source_version,
                "display_path": public_file.get("display_path") or "",
            },
        },
    }


def _audit_drive_write(data_root: Path, action: str, connection_id: str, result: dict[str, Any]) -> None:
    file_record = result.get("file") if isinstance(result.get("file"), dict) else {}
    append_audit(
        data_root,
        action,
        "drive_file",
        str(file_record.get("drive_file_id") or ""),
        {
            "provider": GOOGLE_DRIVE_PROVIDER,
            "connection_id": connection_id,
            "stable_storage_file_id": file_record.get("stable_storage_file_id") or file_record.get("file_id"),
            "drive_file_id": file_record.get("drive_file_id"),
            "status": result.get("status"),
        },
    )


def _drive_content_from_body(body: dict[str, Any]) -> tuple[bytes, str]:
    if "content_base64" in body and body.get("content_base64") is not None:
        try:
            content = b64decode(str(body.get("content_base64") or ""), validate=True)
        except (binascii.Error, ValueError) as error:
            raise StorageValidationError("content_base64 must be valid base64.", operation="drive_write") from error
        return content, str(body.get("content_type") or "application/octet-stream")
    if "content" in body and body.get("content") is not None:
        return str(body.get("content") or "").encode("utf-8"), str(body.get("content_type") or "text/plain; charset=utf-8")
    raise StorageValidationError(
        "Drive write requires content or content_base64.",
        operation="drive_write",
        expected_fields=["content", "content_base64"],
    )


def _require_delete_confirmation(body: dict[str, Any]) -> None:
    policy = str(body.get("delete_policy") or "").strip().lower()
    if _bool_value(body.get("confirm")) or policy in {"user_confirmed", "workspace_policy", "explicit_policy"}:
        return
    raise StorageValidationError(
        "Google Drive trash/delete requires confirm=true or an explicit delete_policy.",
        operation="drive_trash",
        expected_fields=["confirm"],
        allowed_values={"delete_policy": ["user_confirmed", "workspace_policy", "explicit_policy"]},
    )


def _redacted_provider_error(error: DriveProviderError) -> str:
    return f"Google Drive change feed request failed with provider status {error.status_code}."
