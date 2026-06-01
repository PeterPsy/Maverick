"""CRM service actions shared by backend, CLI, MCP, and hooks."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from errors import ValidationError
from domains.account_insights import account_brief, summarize_account
from domains.action_catalog import app_events_for_action, operations_manifest
from domains.automation_rules import (
    create_automation_rule,
    list_automation_rules,
    run_automation_rules,
    update_automation_rule,
)
from domains.bootstrap import bootstrap_payload
from domains.record_intelligence import intelligent_next_actions, propose_workflows, record_enrichment
from domains.custom_fields import (
    archive_custom_field,
    define_custom_field,
    list_custom_fields,
    schema_config,
    set_custom_fields,
)
from domains.external_refs import (
    link_external_ref,
    list_external_refs,
    unlink_external_ref,
)
from domains.health import health_report as domain_health_report
from domains.import_export import import_commit, import_preview
from domains.operations import audit_log, find_duplicates, list_next_actions
from domains.operations_feed import operations_feed
from domains.pipeline import create_pipeline, create_pipeline_stage, delete_pipeline_stage, move_deal, pipeline_board, update_pipeline, update_pipeline_stage
from domains.record_lifecycle import (
    record_exists,
)
from domains.record_maintenance import (
    archive_record,
    bulk_update,
    delete_record,
    merge_records,
    tag_record,
    unarchive_record,
    untag_record,
)
from domains.record_mutations import (
    convert_lead,
    create_account,
    create_contact,
    create_deal,
    create_lead,
    create_note,
    create_task,
    log_activity,
    update_account,
    update_contact,
    update_deal,
    update_lead,
    update_note,
    update_task,
)
from domains.record_queries import filter_records, search, view_entity_type
from domains.records import records_table
from domains.references import reference_manifest, reference_resolve, reference_search, reference_summarize
from domains.reports import sales_reports
from domains.saved_views import apply_saved_view, delete_saved_view, list_saved_views, read_view_state, save_view, write_view_state
from domains.timeline import external_timeline, timeline
from domains.website_intake import ingest_website_intake
from domains.workflow import approve_workflow_proposal, dismiss_workflow_proposal, list_workflow_proposals
from domains.workflow_actions import apply_workflow_proposal, workflow_proposal_action_issues, workflow_proposal_preview
from store import (
    connect,
    export_payload,
    get_record,
    initialize,
    require_text,
    utc_now,
)


def handle_action(data_root: str | Path, action: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    initialize(data_root)
    try:
        with connect(data_root) as db:
            if action in {"operations.manifest", "crm.manifest"}:
                return 200, operations_manifest()
            if action in {"health", "crm.health"}:
                return 200, health_report(db, data_root)
            if action in {"bootstrap", "crm.bootstrap"}:
                return 200, bootstrap_payload(db, data_root)
            if action in {"crm.schema", "schema", "crm.config", "config"}:
                return 200, schema_config(db)
            if action in {"crm.search", "search"}:
                return 200, search(db, payload)
            if action in {"crm.records_table", "records_table"}:
                return 200, records_table(db, payload)
            if action in {"crm.get_record", "get_record"}:
                return 200, {"record": get_record(db, require_text(payload, "entity_type", required=True), require_text(payload, "id", required=True))}
            if action in {"crm.create_lead", "create_lead"}:
                return 201, {"lead": create_lead(db, payload)}
            if action in {"crm.website_intake", "crm.ingest_website_intake", "website_intake"}:
                return 201, ingest_website_intake(db, payload)
            if action in {"crm.update_lead", "update_lead"}:
                return 200, {"lead": update_lead(db, payload)}
            if action in {"crm.convert_lead", "convert_lead"}:
                return 200, convert_lead(db, payload)
            if action in {"crm.create_account", "create_account"}:
                return 201, {"account": create_account(db, payload)}
            if action in {"crm.update_account", "update_account"}:
                return 200, {"account": update_account(db, payload)}
            if action in {"crm.create_contact", "create_contact"}:
                return 201, {"contact": create_contact(db, payload)}
            if action in {"crm.update_contact", "update_contact"}:
                return 200, {"contact": update_contact(db, payload)}
            if action in {"crm.create_deal", "create_deal"}:
                return 201, {"deal": create_deal(db, payload)}
            if action in {"crm.update_deal", "update_deal"}:
                return 200, {"deal": update_deal(db, payload)}
            if action in {"crm.move_deal", "move_deal"}:
                return 200, {"deal": move_deal(db, payload)}
            if action in {"crm.pipeline_board", "pipeline_board"}:
                return 200, pipeline_board(db, payload)
            if action in {"crm.create_pipeline", "create_pipeline"}:
                return 201, {"pipeline": create_pipeline(db, payload)}
            if action in {"crm.update_pipeline", "update_pipeline"}:
                return 200, {"pipeline": update_pipeline(db, payload)}
            if action in {"crm.create_pipeline_stage", "create_pipeline_stage"}:
                return 201, {"stage": create_pipeline_stage(db, payload)}
            if action in {"crm.update_pipeline_stage", "update_pipeline_stage"}:
                return 200, {"stage": update_pipeline_stage(db, payload)}
            if action in {"crm.delete_pipeline_stage", "delete_pipeline_stage"}:
                return 200, delete_pipeline_stage(db, payload)
            if action in {"crm.log_activity", "log_activity"}:
                return 201, {"activity": log_activity(db, payload)}
            if action in {"crm.create_task", "create_task"}:
                return 201, {"task": create_task(db, payload)}
            if action in {"crm.update_task", "update_task"}:
                return 200, {"task": update_task(db, payload)}
            if action in {"crm.create_note", "create_note"}:
                return 201, {"note": create_note(db, payload)}
            if action in {"crm.update_note", "update_note"}:
                return 200, {"note": update_note(db, payload)}
            if action in {"crm.list_next_actions", "list_next_actions"}:
                return 200, {"tasks": list_next_actions(db, payload)}
            if action in {"crm.operations_feed", "operations_feed"}:
                return 200, operations_feed(db, payload)
            if action in {"crm.archive_record", "archive_record"}:
                return 200, {"record": archive_record(db, payload)}
            if action in {"crm.unarchive_record", "unarchive_record"}:
                return 200, {"record": unarchive_record(db, payload)}
            if action in {"crm.delete_record", "delete_record"}:
                return 200, delete_record(db, payload)
            if action in {"crm.tag_record", "tag_record"}:
                return 200, {"record": tag_record(db, payload)}
            if action in {"crm.untag_record", "untag_record"}:
                return 200, {"record": untag_record(db, payload)}
            if action in {"crm.bulk_update", "bulk_update"}:
                return 200, bulk_update(db, payload)
            if action in {"crm.merge_records", "merge_records", "crm_merge_records"}:
                return 200, merge_records(db, payload)
            if action in {"crm.timeline", "timeline"}:
                return 200, timeline(db, payload)
            if action in {"crm.audit_log", "audit_log", "crm_audit_log"}:
                return 200, audit_log(db, payload)
            if action in {"crm.sales_reports", "sales_reports", "crm_sales_reports"}:
                return 200, sales_reports(db, payload)
            if action in {"crm.filter_records", "filter_records"}:
                return 200, filter_records(db, payload)
            if action in {"crm.find_duplicates", "find_duplicates"}:
                return 200, find_duplicates(db, payload)
            if action in {"crm.list_saved_views", "list_saved_views"}:
                return 200, {"saved_views": list_saved_views(db)}
            if action in {"crm.save_view", "save_view"}:
                return 200, {"saved_view": save_view(db, payload)}
            if action in {"crm.delete_saved_view", "delete_saved_view"}:
                return 200, delete_saved_view(db, payload)
            if action in {"crm.apply_saved_view", "apply_saved_view"}:
                return 200, {"state": apply_saved_view(db, data_root, payload)}
            if action in {"crm.list_custom_fields", "list_custom_fields"}:
                return 200, {"custom_fields": list_custom_fields(db, view_entity_type(payload) if payload.get("entity_type") else "")}
            if action in {"crm.define_custom_field", "define_custom_field"}:
                return 200, {"custom_field": define_custom_field(db, payload)}
            if action in {"crm.archive_custom_field", "archive_custom_field"}:
                return 200, {"custom_field": archive_custom_field(db, payload)}
            if action in {"crm.set_custom_fields", "set_custom_fields"}:
                return 200, {"record": set_custom_fields(db, payload)}
            if action in {"crm.list_automation_rules", "list_automation_rules"}:
                return 200, {"automation_rules": list_automation_rules(db)}
            if action in {"crm.create_automation_rule", "create_automation_rule"}:
                return 201, {"automation_rule": create_automation_rule(db, payload)}
            if action in {"crm.update_automation_rule", "update_automation_rule"}:
                return 200, {"automation_rule": update_automation_rule(db, payload)}
            if action in {"crm.record_enrichment", "record_enrichment"}:
                return 200, record_enrichment(db, payload)
            if action in {"crm.intelligent_next_actions", "intelligent_next_actions"}:
                return 200, {"actions": intelligent_next_actions(db, payload)}
            if action in {"crm.propose_workflows", "propose_workflows"}:
                return 200, propose_workflows(db, payload)
            if action in {"crm.run_automation_rules", "run_automation_rules"}:
                return 200, run_automation_rules(db, payload)
            if action in {"crm.list_workflow_proposals", "list_workflow_proposals"}:
                return 200, {"workflow_proposals": list_workflow_proposals(db, payload)}
            if action in {"crm.workflow_proposal_preview", "workflow_proposal_preview"}:
                return 200, workflow_proposal_preview(db, payload)
            if action in {"crm.approve_workflow_proposal", "approve_workflow_proposal"}:
                return 200, {"workflow_proposal": approve_workflow_proposal(db, payload)}
            if action in {"crm.dismiss_workflow_proposal", "dismiss_workflow_proposal", "crm.reject_workflow_proposal", "reject_workflow_proposal"}:
                if action in {"crm.reject_workflow_proposal", "reject_workflow_proposal"}:
                    payload = {**payload, "status": "rejected"}
                return 200, {"workflow_proposal": dismiss_workflow_proposal(db, payload)}
            if action in {"crm.apply_workflow_proposal", "apply_workflow_proposal"}:
                return 200, apply_workflow_proposal(db, payload)
            if action in {"crm.link_external_ref", "link_external_ref", "crm_link_external_ref"}:
                return 200, {"external_ref": link_external_ref(db, payload)}
            if action in {"crm.unlink_external_ref", "unlink_external_ref", "crm_unlink_external_ref"}:
                return 200, unlink_external_ref(db, payload)
            if action in {"crm.list_external_refs", "list_external_refs", "crm_list_external_refs"}:
                return 200, {"external_refs": list_external_refs(db, payload)}
            if action in {"crm.external_timeline", "external_timeline", "crm_external_timeline"}:
                return 200, external_timeline(db, payload)
            if action in {"crm.summarize_account", "summarize_account"}:
                return 200, summarize_account(db, require_text(payload, "account_id", required=True))
            if action in {"crm.account_brief", "account_brief"}:
                return 200, account_brief(db, require_text(payload, "account_id", required=True))
            if action in {"crm.import_preview", "import_preview"}:
                return 200, import_preview(payload)
            if action in {"crm.import_commit", "import_commit"}:
                return 200, import_commit(
                    db,
                    payload,
                    {
                        "lead": create_lead,
                        "account": create_account,
                        "contact": create_contact,
                        "deal": create_deal,
                        "activity": log_activity,
                        "task": create_task,
                        "note": create_note,
                    },
                )
            if action in {"crm.export", "export"}:
                return 200, {"ok": True, "export": export_payload(db)}
            if action in {"crm_reference_manifest", "references.manifest"}:
                return 200, reference_manifest()
            if action in {"crm_reference_search", "references.search"}:
                return 200, reference_search(db, payload, search)
            if action in {"crm_reference_resolve", "references.resolve"}:
                return 200, reference_resolve(db, payload)
            if action in {"crm_reference_summarize", "references.summarize"}:
                return 200, reference_summarize(db, payload)
            if action in {"view_filter", "crm.view_filter"}:
                return 200, {"state": read_view_state(data_root)}
            if action in {"set_view_filter", "crm.set_view_filter"}:
                return 200, {"state": write_view_state(data_root, {"mode": "search", "query": require_text(payload, "query"), "entity_type": view_entity_type(payload), "refs": [], "title": "", "updated_at": utc_now()})}
            if action in {"set_custom_view", "crm.set_custom_view"}:
                refs = payload.get("refs") or []
                if not isinstance(refs, list):
                    raise ValidationError("`refs` must be an array.")
                return 200, {"state": write_view_state(data_root, {"mode": "custom", "query": "", "entity_type": "all", "refs": refs, "title": require_text(payload, "title"), "updated_at": utc_now()})}
            if action in {"clear_custom_view", "crm.clear_custom_view"}:
                return 200, {"state": write_view_state(data_root, {"mode": "search", "query": "", "entity_type": "all", "refs": [], "title": "", "updated_at": utc_now()})}
            raise ValidationError(f"Unsupported action `{action}`.")
    except sqlite3.IntegrityError as error:
        raise ValidationError("CRM record violates a uniqueness or integrity constraint.", details={"reason": str(error)}) from error


def health_report(db, data_root: str | Path) -> dict[str, Any]:
    return domain_health_report(
        db,
        data_root,
        read_view_state=read_view_state,
        import_preview=import_preview,
        workflow_proposal_action_issues=workflow_proposal_action_issues,
        record_exists=record_exists,
    )
