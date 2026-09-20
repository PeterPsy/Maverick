"""Storage MCP request handling shared by ordinary and reusable entrypoints."""

from pathlib import Path

from errors import StorageConflictError, StorageValidationError, conflict_error_payload, validation_error_payload
from operations_manifest import STORAGE_ACTION_ALIASES
from service import app_events_for_result, handle_action, secret_lookup_for_drive_action


TOOL_ACTIONS = {
    "storage_list_files": "catalog",
    "storage_file_info": "file_info",
    "storage_read_file": "file.content.read",
    "storage_read_text": "file.text.read",
    "storage_preview_text": "file.preview.text",
    "storage_preview_table": "file.preview.table",
    "storage_reference_manifest": "references.manifest",
    "storage_reference_search": "references.search",
    "storage_reference_resolve": "references.resolve",
    "storage_reference_summarize": "references.summarize",
    "storage_view_filter": "view_filter",
    "storage_set_view_filter": "set_view_filter",
    "storage_set_custom_view": "set_custom_view",
    "storage_clear_custom_view": "clear_custom_view",
    "storage_write_file": "file.content.write",
    "storage_update_markdown_file": "update_markdown_file",
    "storage_image_inspect": "image.inspect",
    "storage_image_compose_pair": "image.compose_pair",
    "storage_drive_connections_list": "drive_connections.list",
    "storage_drive_connections_start_oauth": "drive_connections.start_oauth",
    "storage_drive_connections_disconnect": "drive_connections.disconnect",
    "storage_drive_list_roots": "drive_list_roots",
    "storage_drive_list_children": "drive_list_children",
    "storage_drive_sync": "drive_sync",
    "storage_drive_search": "drive_search",
    "storage_drive_read": "drive_read",
    "storage_drive_preview": "drive_preview",
    "storage_drive_export": "drive_export",
    "storage_file_localize": "file.localize",
    "storage_file_localize_status": "file.localize_status",
    "storage_file_localize_retry": "file.localize_retry",
    "storage_file_localize_cancel": "file.localize_cancel",
    "storage_file_reconcile": "file.reconcile",
    "storage_drive_index": "drive_index",
    "storage_drive_mark_indexed": "drive_mark_indexed",
    "storage_drive_write": "drive_write",
    "storage_drive_rename": "drive_rename",
    "storage_drive_move": "drive_move",
    "storage_drive_trash": "drive_trash",
}


def handle_payload(payload: dict) -> dict:
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    tool_name = str(payload.get("tool_name") or "")
    raw_action = TOOL_ACTIONS.get(tool_name) or str(arguments.get("action") or "operations.manifest")
    requested_action = STORAGE_ACTION_ALIASES.get(raw_action, raw_action)
    body = {
        **arguments,
        "_app_secrets": payload.get("app_secrets", {}),
        "_surface": str(payload.get("surface") or "mcp"),
        "_effective_mode": str(payload.get("effective_mode") or "sandbox"),
        "action": requested_action,
    }
    if payload.get("surface") == "secret_selector":
        return secret_lookup_for_drive_action(
            Path(payload["data_root"]), Path(payload["uploaded_storage_root"]),
            Path(payload["generated_storage_root"]), body,
        )

    try:
        status_code, result = handle_action(
            Path(payload["data_root"]),
            Path(payload["uploaded_storage_root"]),
            Path(payload["generated_storage_root"]),
            body,
        )
    except StorageConflictError as error:
        status_code, result = 409, conflict_error_payload(error)
    except StorageValidationError as error:
        status_code, result = 400, validation_error_payload(error)

    response = {"status_code": status_code, **result}
    if status_code < 400:
        response["app_events"] = app_events_for_result(str(body.get("action") or "catalog"), result)
    return response
