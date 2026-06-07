"""Storage app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import StorageValidationError, validation_error_payload
from operations_manifest import STORAGE_ACTION_ALIASES
from service import app_events_for_action, handle_action, secret_lookup_for_drive_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_actions = {
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
    "storage_drive_index": "drive_index",
    "storage_drive_mark_indexed": "drive_mark_indexed",
    "storage_drive_write": "drive_write",
    "storage_drive_rename": "drive_rename",
    "storage_drive_move": "drive_move",
    "storage_drive_trash": "drive_trash",
}
tool_name = str(payload.get("tool_name") or "")
raw_action = tool_actions.get(tool_name) or str(arguments.get("action") or "operations.manifest")
requested_action = STORAGE_ACTION_ALIASES.get(raw_action, raw_action)
body = {**arguments, "_app_secrets": payload.get("app_secrets", {}), "action": requested_action}
if payload.get("surface") == "secret_selector":
    print(
        json.dumps(
            secret_lookup_for_drive_action(
                Path(payload["data_root"]),
                Path(payload["uploaded_storage_root"]),
                Path(payload["generated_storage_root"]),
                body,
            ),
            ensure_ascii=False,
        )
    )
    raise SystemExit(0)
try:
    status_code, result = handle_action(
        Path(payload["data_root"]),
        Path(payload["uploaded_storage_root"]),
        Path(payload["generated_storage_root"]),
        body,
    )
except StorageValidationError as error:
    status_code, result = 400, validation_error_payload(error)

response = {"status_code": status_code, **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(str(body.get("action") or "catalog"))
print(json.dumps(response, ensure_ascii=False))
