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
    "crm_create_lead": "crm.create_lead",
    "crm_update_lead": "crm.update_lead",
    "crm_convert_lead": "crm.convert_lead",
    "crm_create_contact": "crm.create_contact",
    "crm_update_contact": "crm.update_contact",
    "crm_create_account": "crm.create_account",
    "crm_update_account": "crm.update_account",
    "crm_create_deal": "crm.create_deal",
    "crm_update_deal": "crm.update_deal",
    "crm_move_deal": "crm.move_deal",
    "crm_create_pipeline": "crm.create_pipeline",
    "crm_update_pipeline": "crm.update_pipeline",
    "crm_create_pipeline_stage": "crm.create_pipeline_stage",
    "crm_update_pipeline_stage": "crm.update_pipeline_stage",
    "crm_log_activity": "crm.log_activity",
    "crm_create_task": "crm.create_task",
    "crm_update_task": "crm.update_task",
    "crm_create_note": "crm.create_note",
    "crm_update_note": "crm.update_note",
    "crm_archive_record": "crm.archive_record",
    "crm_unarchive_record": "crm.unarchive_record",
    "crm_delete_record": "crm.delete_record",
    "crm_tag_record": "crm.tag_record",
    "crm_untag_record": "crm.untag_record",
    "crm_bulk_update": "crm.bulk_update",
    "crm_merge_records": "crm.merge_records",
    "crm_timeline": "crm.timeline",
    "crm_audit_log": "crm.audit_log",
    "crm_sales_reports": "crm.sales_reports",
    "crm_filter_records": "crm.filter_records",
    "crm_find_duplicates": "crm.find_duplicates",
    "crm_list_saved_views": "crm.list_saved_views",
    "crm_save_view": "crm.save_view",
    "crm_delete_saved_view": "crm.delete_saved_view",
    "crm_apply_saved_view": "crm.apply_saved_view",
    "crm_schema": "crm.schema",
    "crm_list_custom_fields": "crm.list_custom_fields",
    "crm_define_custom_field": "crm.define_custom_field",
    "crm_archive_custom_field": "crm.archive_custom_field",
    "crm_set_custom_fields": "crm.set_custom_fields",
    "crm_list_automation_rules": "crm.list_automation_rules",
    "crm_create_automation_rule": "crm.create_automation_rule",
    "crm_update_automation_rule": "crm.update_automation_rule",
    "crm_record_enrichment": "crm.record_enrichment",
    "crm_intelligent_next_actions": "crm.intelligent_next_actions",
    "crm_propose_workflows": "crm.propose_workflows",
    "crm_run_automation_rules": "crm.run_automation_rules",
    "crm_list_workflow_proposals": "crm.list_workflow_proposals",
    "crm_approve_workflow_proposal": "crm.approve_workflow_proposal",
    "crm_apply_workflow_proposal": "crm.apply_workflow_proposal",
    "crm_link_external_ref": "crm.link_external_ref",
    "crm_unlink_external_ref": "crm.unlink_external_ref",
    "crm_list_external_refs": "crm.list_external_refs",
    "crm_external_timeline": "crm.external_timeline",
    "crm_list_next_actions": "crm.list_next_actions",
    "crm_summarize_account": "crm.summarize_account",
    "crm_account_brief": "crm.account_brief",
    "crm_export": "crm.export",
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
