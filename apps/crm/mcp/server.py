"""MCP entrypoint for the CRM app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from errors import CrmError, error_payload
from service import app_events_for_action, handle_action

TOOL_ACTIONS = {
    "crm_search": "crm.search",
    "crm_get_record": "crm.get_record",
    "crm_create_contact": "crm.create_contact",
    "crm_update_contact": "crm.update_contact",
    "crm_create_account": "crm.create_account",
    "crm_update_account": "crm.update_account",
    "crm_create_deal": "crm.create_deal",
    "crm_update_deal": "crm.update_deal",
    "crm_move_deal": "crm.move_deal",
    "crm_log_activity": "crm.log_activity",
    "crm_create_task": "crm.create_task",
    "crm_update_task": "crm.update_task",
    "crm_create_note": "crm.create_note",
    "crm_update_note": "crm.update_note",
    "crm_list_next_actions": "crm.list_next_actions",
    "crm_summarize_account": "crm.summarize_account",
    "crm_import_preview": "crm.import_preview",
    "crm_import_commit": "crm.import_commit",
    "crm_health": "crm.health",
    "crm_reference_manifest": "crm_reference_manifest",
    "crm_reference_search": "crm_reference_search",
    "crm_reference_resolve": "crm_reference_resolve",
    "crm_reference_summarize": "crm_reference_summarize",
    "crm_view_filter": "view_filter",
    "crm_set_view_filter": "set_view_filter",
    "crm_set_custom_view": "set_custom_view",
    "crm_clear_custom_view": "clear_custom_view",
}

payload = read_entrypoint_payload()
tool_name = str(payload.raw.get("tool_name") or "")
action = TOOL_ACTIONS.get(tool_name) or str(payload.arguments.get("action") or "operations.manifest")
try:
    status_code, result = handle_action(payload.data_root, action, payload.arguments)
except CrmError as error:
    status_code, result = error.status_code, error_payload(error)

response = {"status_code": status_code, "app_id": "crm", "workspace_id": payload.workspace_id, "tool_name": tool_name, **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
