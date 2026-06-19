"""MCP entrypoint for `mail`."""

from __future__ import annotations

from pathlib import Path
import sys

for parent in Path(__file__).resolve().parents:
    if (parent / "core").is_dir():
        sys.path.insert(0, str(parent))
        break

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action, resolve_secret_resource, resolve_secret_resource_inventory


TOOL_ACTIONS = {
    "mail_reference_manifest": "reference_manifest",
    "mail_reference_search": "reference_search",
    "mail_reference_resolve": "reference_resolve",
    "mail_reference_summarize": "reference_summarize",
    "mail_view_filter": "view_filter",
    "mail_set_view_filter": "set_view_filter",
    "mail_set_custom_view": "set_custom_view",
    "mail_clear_custom_view": "clear_custom_view",
    "mail_list_threads": "mail_list_threads",
    "mail_get_thread": "mail_get_thread",
    "mail_search_messages": "mail_search_messages",
    "mail_create_draft": "mail_create_draft",
    "mail_update_draft": "mail_update_draft",
    "mail_send_draft": "mail_send_draft",
    "mail_send_draft_approved": "mail_send_draft_approved",
    "mail_send": "mail_send",
    "mail_send_approved": "mail_send_approved",
    "mail_modify_labels": "mail_modify_labels",
    "mail_mark_read": "mail_mark_read",
    "mail_get_attachment": "mail_get_attachment",
    "mail_save_attachments": "mail_save_attachments",
    "mail_sync": "mail_sync",
}


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
if payload.raw.get("surface") == "secret_resource_inventory":
    emit_json(resolve_secret_resource_inventory(Path(payload.data_root)))
    raise SystemExit(0)
if payload.raw.get("surface") == "secret_selector":
    tool_name = str(payload.raw.get("tool_name") or "")
    arguments.setdefault("action", TOOL_ACTIONS.get(tool_name, "mail_list_threads"))
    arguments["_app_secret_selector"] = payload.raw.get("app_secret_selector", {})
    emit_json(resolve_secret_resource(Path(payload.data_root), arguments))
    raise SystemExit(0)
arguments["_app_secrets"] = payload.raw.get("app_secrets", {})
arguments["_generated_storage_root"] = payload.raw.get("generated_storage_root", "")
arguments["_uploaded_storage_root"] = payload.raw.get("uploaded_storage_root", "")
arguments["_workspace_id"] = payload.workspace_id
tool_name = str(payload.raw.get("tool_name") or "")
arguments.setdefault("action", TOOL_ACTIONS.get(tool_name, "mail_list_threads"))
status_code, result = handle_action(Path(payload.data_root), arguments)
result["status_code"] = status_code
if status_code < 400:
    result.setdefault("app_id", payload.app_id)
    result.setdefault("workspace_id", payload.workspace_id)
    result.setdefault("tool_name", tool_name)
    result["app_events"] = app_events_for_action(str(arguments.get("action") or "list"), result)
emit_json(result)
