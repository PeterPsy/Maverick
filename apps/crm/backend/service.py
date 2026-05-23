"""CRM service actions shared by backend, CLI, MCP, and hooks."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
from typing import Any

from errors import NotFoundError, ValidationError
from domains.health import health_report as domain_health_report
from domains.import_export import import_preview, _looks_like_export_payload, _map_import_row, _normalize_import_payload, _read_import_rows, _validate_import_rows
from domains.operations import audit_log, find_duplicates, list_next_actions
from domains.pipeline import create_pipeline, create_pipeline_stage, move_deal, update_pipeline, update_pipeline_stage, _require_pipeline, _stage_name, _stage_probability, _write_deal_update
from domains.record_lifecycle import (
    ensure_no_dependents,
    get_non_deleted_record,
    note_title,
    record_exists,
    reindex_record,
    title_for_record,
    validate_relationships,
)
from domains.records import records_table
from domains.references import reference_manifest, reference_resolve, reference_search, reference_summarize
from domains.reports import sales_reports
from domains.saved_views import apply_saved_view, delete_saved_view, list_saved_views, read_view_state, save_view, write_view_state
from domains.workflow import approve_workflow_proposal, list_workflow_proposals, _create_workflow_proposal, _workflow_proposal, _workflow_proposal_duplicate_exists
from store import (
    CUSTOM_FIELD_TYPES,
    SCHEMA_VERSION,
    attach_tags,
    connect,
    count_tables,
    delete_fts,
    export_payload,
    get_record,
    initialize,
    list_rows,
    metadata,
    new_id,
    parse_limit,
    require_text,
    row_to_dict,
    table_for_entity,
    upsert_fts,
    utc_now,
    write_event,
)


WRITE_ACTIONS = {
    "crm.create_account",
    "create_account",
    "crm.update_account",
    "update_account",
    "crm.create_lead",
    "create_lead",
    "crm.update_lead",
    "update_lead",
    "crm.convert_lead",
    "convert_lead",
    "crm.create_contact",
    "create_contact",
    "crm.update_contact",
    "update_contact",
    "crm.create_deal",
    "create_deal",
    "crm.update_deal",
    "update_deal",
    "crm.move_deal",
    "move_deal",
    "crm.create_pipeline",
    "create_pipeline",
    "crm.update_pipeline",
    "update_pipeline",
    "crm.create_pipeline_stage",
    "create_pipeline_stage",
    "crm.update_pipeline_stage",
    "update_pipeline_stage",
    "crm.log_activity",
    "log_activity",
    "crm.create_task",
    "create_task",
    "crm.update_task",
    "update_task",
    "crm.create_note",
    "create_note",
    "crm.update_note",
    "update_note",
    "crm.archive_record",
    "archive_record",
    "crm.unarchive_record",
    "unarchive_record",
    "crm.delete_record",
    "delete_record",
    "crm.tag_record",
    "tag_record",
    "crm.untag_record",
    "untag_record",
    "crm.bulk_update",
    "bulk_update",
    "crm.merge_records",
    "merge_records",
    "crm_merge_records",
    "crm.import_commit",
    "import_commit",
    "crm.save_view",
    "save_view",
    "crm.delete_saved_view",
    "delete_saved_view",
    "crm.apply_saved_view",
    "apply_saved_view",
    "crm.define_custom_field",
    "define_custom_field",
    "crm.archive_custom_field",
    "archive_custom_field",
    "crm.set_custom_fields",
    "set_custom_fields",
    "crm.create_automation_rule",
    "create_automation_rule",
    "crm.update_automation_rule",
    "update_automation_rule",
    "crm.record_enrichment",
    "record_enrichment",
    "crm.propose_workflows",
    "propose_workflows",
    "crm.run_automation_rules",
    "run_automation_rules",
    "crm.approve_workflow_proposal",
    "approve_workflow_proposal",
    "crm.apply_workflow_proposal",
    "apply_workflow_proposal",
    "crm.link_external_ref",
    "link_external_ref",
    "crm_link_external_ref",
    "crm.unlink_external_ref",
    "unlink_external_ref",
    "crm_unlink_external_ref",
    "crm.set_view_filter",
    "set_view_filter",
    "crm.set_custom_view",
    "set_custom_view",
    "crm.clear_custom_view",
    "clear_custom_view",
}

ENTITY_TABLES = {
    "lead": "leads",
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "task": "tasks",
    "note": "notes",
}
TABLE_ENTITY_TYPES = {table: entity_type for entity_type, table in ENTITY_TABLES.items()}
EXPORT_ENTITY_ORDER = ["leads", "accounts", "contacts", "deals", "activities", "tasks", "notes"]
EXPORT_CONFIG_TABLES = ["custom_field_definitions", "custom_field_values", "automation_rules", "workflow_proposals", "external_refs"]
VIEW_ENTITY_TYPES = {"all", "lead", "account", "contact", "deal", "activity", "task", "note"}
FIELD_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action in WRITE_ACTIONS:
        resource = "view-state" if "view" in action or "custom_view" in action else "records"
        return [{"type": "maverick.app.data-changed", "owner_app_id": "crm", "resource": resource}]
    return []


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
            if action in {"crm.create_pipeline", "create_pipeline"}:
                return 201, {"pipeline": create_pipeline(db, payload)}
            if action in {"crm.update_pipeline", "update_pipeline"}:
                return 200, {"pipeline": update_pipeline(db, payload)}
            if action in {"crm.create_pipeline_stage", "create_pipeline_stage"}:
                return 201, {"stage": create_pipeline_stage(db, payload)}
            if action in {"crm.update_pipeline_stage", "update_pipeline_stage"}:
                return 200, {"stage": update_pipeline_stage(db, payload)}
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
            if action in {"crm.approve_workflow_proposal", "approve_workflow_proposal"}:
                return 200, {"workflow_proposal": approve_workflow_proposal(db, payload)}
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
                return 200, import_commit(db, payload)
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


def operations_manifest() -> dict[str, Any]:
    return {
        "ok": True,
        "app_id": "crm",
        "default_action": "operations.manifest",
        "entities": ["lead", "account", "contact", "deal", "activity", "task", "note"],
        "actions": [
            "crm.search",
            "crm.records_table",
            "crm.get_record",
            "crm.create_lead",
            "crm.update_lead",
            "crm.convert_lead",
            "crm.create_contact",
            "crm.update_contact",
            "crm.create_account",
            "crm.update_account",
            "crm.create_deal",
            "crm.update_deal",
            "crm.move_deal",
            "crm.create_pipeline",
            "crm.update_pipeline",
            "crm.create_pipeline_stage",
            "crm.update_pipeline_stage",
            "crm.log_activity",
            "crm.create_task",
            "crm.update_task",
            "crm.create_note",
            "crm.update_note",
            "crm.archive_record",
            "crm.unarchive_record",
            "crm.delete_record",
            "crm.tag_record",
            "crm.untag_record",
            "crm.bulk_update",
            "crm.merge_records",
            "crm.timeline",
            "crm.audit_log",
            "crm.sales_reports",
            "crm.filter_records",
            "crm.find_duplicates",
            "crm.list_saved_views",
            "crm.save_view",
            "crm.delete_saved_view",
            "crm.apply_saved_view",
            "crm.schema",
            "crm.list_custom_fields",
            "crm.define_custom_field",
            "crm.archive_custom_field",
            "crm.set_custom_fields",
            "crm.list_automation_rules",
            "crm.create_automation_rule",
            "crm.update_automation_rule",
            "crm.record_enrichment",
            "crm.intelligent_next_actions",
            "crm.propose_workflows",
            "crm.run_automation_rules",
            "crm.list_workflow_proposals",
            "crm.approve_workflow_proposal",
            "crm.apply_workflow_proposal",
            "crm.link_external_ref",
            "crm.unlink_external_ref",
            "crm.list_external_refs",
            "crm.external_timeline",
            "crm.list_next_actions",
            "crm.summarize_account",
            "crm.account_brief",
            "crm.import_preview",
            "crm.import_commit",
            "crm.export",
            "crm.health",
            "crm.view_filter",
            "crm.set_view_filter",
            "crm.set_custom_view",
            "crm.clear_custom_view",
            "crm_reference_manifest",
            "crm_reference_search",
            "crm_reference_resolve",
            "crm_reference_summarize",
        ],
    }


def health_report(db, data_root: str | Path) -> dict[str, Any]:
    return domain_health_report(
        db,
        data_root,
        read_view_state=read_view_state,
        import_preview=import_preview,
        workflow_proposal_action_issues=_workflow_proposal_action_issues,
        record_exists=record_exists,
    )


def view_entity_type(payload: dict[str, Any]) -> str:
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    if entity_type not in VIEW_ENTITY_TYPES:
        raise ValidationError("Unsupported CRM view entity_type.", details={"entity_type": entity_type})
    return entity_type


def _coerce_number(payload: dict[str, Any], key: str, default: float) -> float:
    value = payload.get(key, default)
    if value is None or value == "":
        return float(default)
    if isinstance(value, bool):
        raise ValidationError(f"`{key}` must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"`{key}` must be a number.") from error
    if not math.isfinite(number):
        raise ValidationError(f"`{key}` must be a finite number.")
    return number


def bootstrap_payload(db, data_root: str | Path) -> dict[str, Any]:
    view_state = read_view_state(data_root)
    payload = {
        "ok": True,
        "leads": list_rows(db, "leads", limit=100),
        "accounts": list_rows(db, "accounts", limit=100),
        "contacts": list_rows(db, "contacts", limit=100),
        "deals": list_rows(db, "deals", limit=100),
        "tasks": list_rows(db, "tasks", limit=50),
        "notes": list_rows(db, "notes", limit=50),
        "activities": list_rows(db, "activities", limit=50),
        "pipelines": [row_to_dict(row) for row in db.execute("SELECT * FROM pipelines ORDER BY name").fetchall()],
        "pipeline_stages": [row_to_dict(row) for row in db.execute("SELECT * FROM pipeline_stages ORDER BY position").fetchall()],
        "saved_views": list_saved_views(db),
        "duplicates": find_duplicates(db, {"limit": 10}),
        "schema": schema_config(db),
        "next_action_suggestions": intelligent_next_actions(db, {"limit": 8}),
        "counts": count_tables(db, ["leads", "accounts", "contacts", "deals", "activities", "tasks", "notes"]),
        "view_state": view_state,
    }
    _hydrate_custom_view_records(db, payload, view_state)
    return payload


def _hydrate_custom_view_records(db, payload: dict[str, Any], view_state: dict[str, Any]) -> None:
    view_filter = view_state.get("view_filter") if isinstance(view_state, dict) else {}
    if not isinstance(view_filter, dict) or view_filter.get("mode") != "custom":
        return
    refs = view_filter.get("refs") or []
    if not isinstance(refs, list):
        return
    for ref in refs:
        parsed = _parse_view_ref(ref)
        if parsed is None:
            continue
        entity_type, entity_id = parsed
        table = ENTITY_TABLES.get(entity_type)
        if not table:
            continue
        try:
            record = get_record(db, entity_type, entity_id)
        except NotFoundError:
            continue
        existing_ids = {str(item.get("id")) for item in payload.get(table, []) if isinstance(item, dict)}
        if record["id"] not in existing_ids:
            payload.setdefault(table, []).append(record)


def _parse_view_ref(ref: Any) -> tuple[str, str] | None:
    if not isinstance(ref, dict):
        return None
    entity_type = str(ref.get("entity_type") or "").strip()
    raw_id = str(ref.get("entity_id") or ref.get("id") or "").strip()
    if not entity_type or not raw_id:
        return None
    entity_id = raw_id.split(":", 1)[1] if ":" in raw_id else raw_id
    return entity_type, entity_id


def search(db, payload: dict[str, Any]) -> dict[str, Any]:
    query = require_text(payload, "query")
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    limit = parse_limit(payload, 25)
    if not query:
        tables = list(ENTITY_TABLES.values()) if entity_type == "all" else [table_for_entity(entity_type)]
        return {"results": [{"entity_type": TABLE_ENTITY_TYPES[table], "record": item} for table in tables for item in list_rows(db, table, limit=limit)]}
    pattern = f"{query}*"
    where = ""
    params: list[Any] = [pattern]
    if entity_type != "all":
        where = " AND entity_type = ?"
        params.append(entity_type)
    params.append(limit)
    rows = db.execute(
        f"SELECT entity_type, entity_id, title, body FROM crm_fts WHERE crm_fts MATCH ?{where} LIMIT ?",
        params,
    ).fetchall()
    return {"results": [dict(row) for row in rows]}


def create_lead(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    lead_id = require_text(payload, "id") or new_id("lead")
    first_name = require_text(payload, "first_name")
    last_name = require_text(payload, "last_name")
    display_name = require_text(payload, "display_name") or " ".join(part for part in [first_name, last_name] if part) or require_text(payload, "email", required=True)
    values = (
        lead_id,
        first_name,
        last_name,
        display_name,
        require_text(payload, "email"),
        require_text(payload, "phone"),
        require_text(payload, "company"),
        require_text(payload, "domain"),
        require_text(payload, "source"),
        require_text(payload, "status", default="new") or "new",
        require_text(payload, "owner_id"),
        require_text(payload, "summary"),
        metadata(payload),
        now,
        now,
    )
    db.execute(
        """
        INSERT INTO leads(id, first_name, last_name, display_name, email, phone, company, domain, source, status, owner_id, summary, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    record = get_record(db, "lead", lead_id)
    upsert_fts(db, "lead", lead_id, record["display_name"], f"{record.get('email', '')} {record.get('company', '')} {record.get('domain', '')} {record.get('summary', '')}")
    write_event(db, "lead.created", "lead", lead_id)
    return record


def update_lead(db, payload: dict[str, Any]) -> dict[str, Any]:
    lead_id = require_text(payload, "id", required=True)
    current = get_record(db, "lead", lead_id)
    merged = {
        **current,
        **{
            key: value
            for key, value in payload.items()
            if key in {"first_name", "last_name", "display_name", "email", "phone", "company", "domain", "source", "status", "owner_id", "summary", "metadata"}
        },
    }
    display_name = require_text(merged, "display_name") or " ".join(part for part in [require_text(merged, "first_name"), require_text(merged, "last_name")] if part)
    db.execute(
        """
        UPDATE leads SET first_name = ?, last_name = ?, display_name = ?, email = ?, phone = ?, company = ?, domain = ?,
          source = ?, status = ?, owner_id = ?, summary = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "first_name"),
            require_text(merged, "last_name"),
            display_name,
            require_text(merged, "email"),
            require_text(merged, "phone"),
            require_text(merged, "company"),
            require_text(merged, "domain"),
            require_text(merged, "source"),
            require_text(merged, "status", default="new") or "new",
            require_text(merged, "owner_id"),
            require_text(merged, "summary"),
            metadata(merged),
            utc_now(),
            lead_id,
        ),
    )
    record = get_record(db, "lead", lead_id)
    upsert_fts(db, "lead", lead_id, record["display_name"], f"{record.get('email', '')} {record.get('company', '')} {record.get('domain', '')} {record.get('summary', '')}")
    write_event(db, "lead.updated", "lead", lead_id)
    return record


def convert_lead(db, payload: dict[str, Any]) -> dict[str, Any]:
    lead_id = require_text(payload, "id") or require_text(payload, "lead_id", required=True)
    lead = get_record(db, "lead", lead_id)
    if lead.get("converted_at"):
        return {
            "ok": True,
            "lead": lead,
            "account": get_record(db, "account", str(lead["account_id"])) if lead.get("account_id") else None,
            "contact": get_record(db, "contact", str(lead["contact_id"])) if lead.get("contact_id") else None,
            "deal": get_record(db, "deal", str(lead["deal_id"])) if lead.get("deal_id") else None,
        }

    account_id = require_text(payload, "account_id")
    account = get_record(db, "account", account_id) if account_id else create_account(
        db,
        {
            "name": require_text(payload, "account_name") or str(lead.get("company") or lead.get("display_name")),
            "domain": require_text(payload, "domain") or str(lead.get("domain") or ""),
            "status": "prospect",
            "owner_id": require_text(payload, "owner_id") or str(lead.get("owner_id") or ""),
            "summary": str(lead.get("summary") or ""),
            "metadata": {"converted_from_lead_id": lead_id},
        },
    )
    contact_id = require_text(payload, "contact_id")
    contact = get_record(db, "contact", contact_id) if contact_id else create_contact(
        db,
        {
            "account_id": account["id"],
            "first_name": str(lead.get("first_name") or ""),
            "last_name": str(lead.get("last_name") or ""),
            "display_name": str(lead.get("display_name") or ""),
            "email": str(lead.get("email") or ""),
            "phone": str(lead.get("phone") or ""),
            "owner_id": require_text(payload, "owner_id") or str(lead.get("owner_id") or ""),
            "summary": str(lead.get("summary") or ""),
            "metadata": {"converted_from_lead_id": lead_id},
        },
    )
    deal: dict[str, Any] | None = None
    if bool(payload.get("create_deal", True)):
        deal = create_deal(
            db,
            {
                "account_id": account["id"],
                "contact_id": contact["id"],
                "name": require_text(payload, "deal_name") or f"{account['name']} opportunity",
                "stage_id": require_text(payload, "stage_id", default="qualified") or "qualified",
                "value": _coerce_number(payload, "value", 0),
                "currency": require_text(payload, "currency", default="EUR") or "EUR",
                "close_date": require_text(payload, "close_date"),
                "owner_id": require_text(payload, "owner_id") or str(lead.get("owner_id") or ""),
                "summary": str(lead.get("summary") or ""),
                "metadata": {"converted_from_lead_id": lead_id},
            },
        )
    now = utc_now()
    db.execute(
        """
        UPDATE leads SET status = 'converted', converted_at = ?, account_id = ?, contact_id = ?, deal_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, account["id"], contact["id"], deal["id"] if deal else "", now, lead_id),
    )
    delete_fts(db, "lead", lead_id)
    converted = get_non_deleted_record(db, "lead", lead_id)
    write_event(db, "lead.converted", "lead", lead_id, {"account_id": account["id"], "contact_id": contact["id"], "deal_id": deal["id"] if deal else ""})
    return {"ok": True, "lead": converted, "account": account, "contact": contact, "deal": deal}


def create_account(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    account_id = require_text(payload, "id") or new_id("acct")
    name = require_text(payload, "name", required=True)
    values = (
        account_id,
        name,
        require_text(payload, "domain"),
        require_text(payload, "industry"),
        require_text(payload, "status", default="prospect") or "prospect",
        require_text(payload, "owner_id"),
        require_text(payload, "summary"),
        metadata(payload),
        now,
        now,
    )
    db.execute(
        """
        INSERT INTO accounts(id, name, domain, industry, status, owner_id, summary, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    upsert_fts(db, "account", account_id, name, " ".join(str(value) for value in values[2:7]))
    write_event(db, "account.created", "account", account_id)
    return get_record(db, "account", account_id)


def update_account(db, payload: dict[str, Any]) -> dict[str, Any]:
    account_id = require_text(payload, "id", required=True)
    current = get_record(db, "account", account_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"name", "domain", "industry", "status", "owner_id", "summary", "metadata"}}}
    db.execute(
        """
        UPDATE accounts SET name = ?, domain = ?, industry = ?, status = ?, owner_id = ?, summary = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "name", required=True),
            require_text(merged, "domain"),
            require_text(merged, "industry"),
            require_text(merged, "status", default="prospect"),
            require_text(merged, "owner_id"),
            require_text(merged, "summary"),
            metadata(merged),
            utc_now(),
            account_id,
        ),
    )
    updated = get_record(db, "account", account_id)
    upsert_fts(db, "account", account_id, updated["name"], f"{updated.get('domain', '')} {updated.get('industry', '')} {updated.get('summary', '')}")
    write_event(db, "account.updated", "account", account_id)
    return updated


def create_contact(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    contact_id = require_text(payload, "id") or new_id("cont")
    validate_relationships(db, payload, ("account_id",))
    first_name = require_text(payload, "first_name")
    last_name = require_text(payload, "last_name")
    display_name = require_text(payload, "display_name") or " ".join(part for part in [first_name, last_name] if part) or require_text(payload, "email", required=True)
    values = (
        contact_id,
        require_text(payload, "account_id"),
        first_name,
        last_name,
        display_name,
        require_text(payload, "email"),
        require_text(payload, "phone"),
        require_text(payload, "role"),
        require_text(payload, "owner_id"),
        require_text(payload, "summary"),
        metadata(payload),
        now,
        now,
    )
    db.execute(
        """
        INSERT INTO contacts(id, account_id, first_name, last_name, display_name, email, phone, role, owner_id, summary, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    upsert_fts(db, "contact", contact_id, display_name, " ".join(str(value) for value in values[5:10]))
    write_event(db, "contact.created", "contact", contact_id)
    return get_record(db, "contact", contact_id)


def update_contact(db, payload: dict[str, Any]) -> dict[str, Any]:
    contact_id = require_text(payload, "id", required=True)
    current = get_record(db, "contact", contact_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"account_id", "first_name", "last_name", "display_name", "email", "phone", "role", "owner_id", "summary", "metadata"}}}
    validate_relationships(db, merged, ("account_id",))
    display_name = require_text(merged, "display_name") or " ".join(part for part in [require_text(merged, "first_name"), require_text(merged, "last_name")] if part)
    db.execute(
        """
        UPDATE contacts SET account_id = ?, first_name = ?, last_name = ?, display_name = ?, email = ?, phone = ?, role = ?, owner_id = ?, summary = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "account_id"),
            require_text(merged, "first_name"),
            require_text(merged, "last_name"),
            display_name,
            require_text(merged, "email"),
            require_text(merged, "phone"),
            require_text(merged, "role"),
            require_text(merged, "owner_id"),
            require_text(merged, "summary"),
            metadata(merged),
            utc_now(),
            contact_id,
        ),
    )
    updated = get_record(db, "contact", contact_id)
    upsert_fts(db, "contact", contact_id, updated["display_name"], f"{updated.get('email', '')} {updated.get('role', '')} {updated.get('summary', '')}")
    write_event(db, "contact.updated", "contact", contact_id)
    return updated


def create_deal(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    deal_id = require_text(payload, "id") or new_id("deal")
    validate_relationships(db, payload, ("account_id", "contact_id"))
    pipeline_id = require_text(payload, "pipeline_id", default="pipeline_default") or "pipeline_default"
    _require_pipeline(db, pipeline_id)
    stage_id = require_text(payload, "stage_id", default=require_text(payload, "stage", default="lead")) or "lead"
    stage = _stage_name(db, stage_id, pipeline_id)
    probability = _coerce_number(payload, "probability", _stage_probability(db, stage_id, pipeline_id))
    value = _coerce_number(payload, "value", 0)
    db.execute(
        """
        INSERT INTO deals(id, account_id, contact_id, pipeline_id, stage_id, name, stage, value, currency, probability, close_date, owner_id, summary, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            deal_id,
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            pipeline_id,
            stage_id,
            require_text(payload, "name", required=True),
            stage,
            value,
            require_text(payload, "currency", default="EUR") or "EUR",
            probability,
            require_text(payload, "close_date"),
            require_text(payload, "owner_id"),
            require_text(payload, "summary"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "deal", deal_id)
    upsert_fts(db, "deal", deal_id, record["name"], f"{record.get('stage', '')} {record.get('summary', '')}")
    write_event(db, "deal.created", "deal", deal_id)
    return record


def update_deal(db, payload: dict[str, Any]) -> dict[str, Any]:
    deal_id = require_text(payload, "id", required=True)
    current = get_record(db, "deal", deal_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"account_id", "contact_id", "pipeline_id", "stage_id", "name", "value", "currency", "probability", "close_date", "owner_id", "summary", "metadata"}}}
    return _write_deal_update(db, deal_id, merged, "deal.updated")


def log_activity(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    activity_id = require_text(payload, "id") or new_id("act")
    validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        INSERT INTO activities(id, activity_type, subject, body, account_id, contact_id, deal_id, occurred_at, due_at, completed_at, owner_id, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activity_id,
            require_text(payload, "activity_type", default="note") or "note",
            require_text(payload, "subject", required=True),
            require_text(payload, "body"),
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "occurred_at", default=now) or now,
            require_text(payload, "due_at"),
            require_text(payload, "completed_at"),
            require_text(payload, "owner_id"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "activity", activity_id)
    upsert_fts(db, "activity", activity_id, record["subject"], f"{record.get('body', '')} {record.get('activity_type', '')}")
    write_event(db, "activity.logged", "activity", activity_id)
    return record


def _update_activity(db, payload: dict[str, Any]) -> dict[str, Any]:
    activity_id = require_text(payload, "id", required=True)
    current = get_record(db, "activity", activity_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"activity_type", "subject", "body", "account_id", "contact_id", "deal_id", "occurred_at", "due_at", "completed_at", "owner_id", "metadata"}}}
    validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE activities SET activity_type = ?, subject = ?, body = ?, account_id = ?, contact_id = ?, deal_id = ?,
          occurred_at = ?, due_at = ?, completed_at = ?, owner_id = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "activity_type", default="note") or "note",
            require_text(merged, "subject", required=True),
            require_text(merged, "body"),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "occurred_at", default=utc_now()) or utc_now(),
            require_text(merged, "due_at"),
            require_text(merged, "completed_at"),
            require_text(merged, "owner_id"),
            metadata(merged),
            utc_now(),
            activity_id,
        ),
    )
    record = get_record(db, "activity", activity_id)
    upsert_fts(db, "activity", activity_id, record["subject"], f"{record.get('body', '')} {record.get('activity_type', '')}")
    write_event(db, "activity.updated", "activity", activity_id)
    return record


def create_task(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    task_id = require_text(payload, "id") or new_id("task")
    validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        INSERT INTO tasks(id, title, status, priority, due_at, account_id, contact_id, deal_id, owner_id, body, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            require_text(payload, "title", required=True),
            require_text(payload, "status", default="open") or "open",
            require_text(payload, "priority", default="normal") or "normal",
            require_text(payload, "due_at"),
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "owner_id"),
            require_text(payload, "body"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "task", task_id)
    upsert_fts(db, "task", task_id, record["title"], f"{record.get('body', '')} {record.get('status', '')} {record.get('priority', '')}")
    write_event(db, "task.created", "task", task_id)
    return record


def update_task(db, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = require_text(payload, "id", required=True)
    current = get_record(db, "task", task_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"title", "status", "priority", "due_at", "account_id", "contact_id", "deal_id", "owner_id", "body", "metadata"}}}
    validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE tasks SET title = ?, status = ?, priority = ?, due_at = ?, account_id = ?, contact_id = ?, deal_id = ?,
          owner_id = ?, body = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "title", required=True),
            require_text(merged, "status", default="open") or "open",
            require_text(merged, "priority", default="normal") or "normal",
            require_text(merged, "due_at"),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "owner_id"),
            require_text(merged, "body"),
            metadata(merged),
            utc_now(),
            task_id,
        ),
    )
    record = get_record(db, "task", task_id)
    upsert_fts(db, "task", task_id, record["title"], f"{record.get('body', '')} {record.get('status', '')} {record.get('priority', '')}")
    write_event(db, "task.updated", "task", task_id)
    return record


def create_note(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    note_id = require_text(payload, "id") or new_id("note")
    validate_relationships(db, payload, ("account_id", "contact_id", "deal_id"))
    body = require_text(payload, "body", required=True)
    db.execute(
        """
        INSERT INTO notes(id, body, account_id, contact_id, deal_id, owner_id, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            note_id,
            body,
            require_text(payload, "account_id"),
            require_text(payload, "contact_id"),
            require_text(payload, "deal_id"),
            require_text(payload, "owner_id"),
            metadata(payload),
            now,
            now,
        ),
    )
    record = get_record(db, "note", note_id)
    upsert_fts(db, "note", note_id, note_title(record), body)
    write_event(db, "note.created", "note", note_id)
    return record


def update_note(db, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = require_text(payload, "id", required=True)
    current = get_record(db, "note", note_id)
    merged = {**current, **{key: value for key, value in payload.items() if key in {"body", "account_id", "contact_id", "deal_id", "owner_id", "metadata"}}}
    validate_relationships(db, merged, ("account_id", "contact_id", "deal_id"))
    db.execute(
        """
        UPDATE notes SET body = ?, account_id = ?, contact_id = ?, deal_id = ?, owner_id = ?, metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "body", required=True),
            require_text(merged, "account_id"),
            require_text(merged, "contact_id"),
            require_text(merged, "deal_id"),
            require_text(merged, "owner_id"),
            metadata(merged),
            utc_now(),
            note_id,
        ),
    )
    record = get_record(db, "note", note_id)
    upsert_fts(db, "note", note_id, note_title(record), record["body"])
    write_event(db, "note.updated", "note", note_id)
    return record


def archive_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    record = get_non_deleted_record(db, entity_type, entity_id)
    if record.get("archived_at"):
        return record
    table = table_for_entity(entity_type)
    now = utc_now()
    db.execute(f"UPDATE {table} SET archived_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, entity_id))
    delete_fts(db, entity_type, entity_id)
    write_event(db, f"{entity_type}.archived", entity_type, entity_id)
    return get_non_deleted_record(db, entity_type, entity_id)


def unarchive_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    get_non_deleted_record(db, entity_type, entity_id)
    table = table_for_entity(entity_type)
    now = utc_now()
    db.execute(f"UPDATE {table} SET archived_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, entity_id))
    record = get_record(db, entity_type, entity_id)
    reindex_record(db, entity_type, record)
    write_event(db, f"{entity_type}.unarchived", entity_type, entity_id)
    return record


def delete_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    get_non_deleted_record(db, entity_type, entity_id)
    ensure_no_dependents(db, entity_type, entity_id)
    table = table_for_entity(entity_type)
    now = utc_now()
    db.execute(f"UPDATE {table} SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, entity_id))
    db.execute("DELETE FROM record_tags WHERE record_type = ? AND record_id = ?", (entity_type, entity_id))
    delete_fts(db, entity_type, entity_id)
    write_event(db, f"{entity_type}.deleted", entity_type, entity_id)
    return {"ok": True, "entity_type": entity_type, "id": entity_id, "deleted_at": now}


def tag_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    name = require_text(payload, "tag") or require_text(payload, "name", required=True)
    color = require_text(payload, "color")
    get_non_deleted_record(db, entity_type, entity_id)
    now = utc_now()
    db.execute(
        "INSERT INTO tags(id, name, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET color = excluded.color, updated_at = excluded.updated_at",
        (new_id("tag"), name, color, now, now),
    )
    row = db.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValidationError("CRM tag could not be resolved after upsert.")
    db.execute(
        "INSERT OR IGNORE INTO record_tags(record_type, record_id, tag_id, created_at) VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, str(row["id"]), now),
    )
    write_event(db, f"{entity_type}.tagged", entity_type, entity_id, {"tag": name})
    return get_non_deleted_record(db, entity_type, entity_id)


def untag_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    name = require_text(payload, "tag") or require_text(payload, "name", required=True)
    get_non_deleted_record(db, entity_type, entity_id)
    db.execute(
        """
        DELETE FROM record_tags
        WHERE record_type = ? AND record_id = ? AND tag_id IN (SELECT id FROM tags WHERE name = ?)
        """,
        (entity_type, entity_id, name),
    )
    write_event(db, f"{entity_type}.untagged", entity_type, entity_id, {"tag": name})
    return get_non_deleted_record(db, entity_type, entity_id)


def bulk_update(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not all(isinstance(item, str) and item.strip() for item in ids):
        raise ValidationError("`ids` must be a non-empty array of record ids.")
    operation = require_text(payload, "operation", default="update") or "update"
    updated: list[dict[str, Any]] = []
    for entity_id in ids:
        item_payload = {**payload, "id": entity_id}
        if operation == "archive":
            updated.append(archive_record(db, item_payload))
        elif operation == "delete":
            delete_record(db, item_payload)
        elif operation == "tag":
            updated.append(tag_record(db, item_payload))
        elif operation == "update":
            updated.append(_update_entity_record(db, entity_type, {**(payload.get("changes") or {}), "id": entity_id}))
        else:
            raise ValidationError("Unsupported bulk operation.", details={"operation": operation})
    write_event(db, f"{entity_type}.bulk_{operation}", entity_type, "", {"ids": ids})
    return {"ok": True, "entity_type": entity_type, "operation": operation, "updated_count": len(ids), "records": updated}


def timeline(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    get_record(db, entity_type, entity_id)
    refs = _timeline_refs(db, entity_type, entity_id)
    items: list[dict[str, Any]] = []
    for activity in _timeline_rows(db, "activity", "activities", refs):
        activity["timestamp"] = activity.get("occurred_at") or activity.get("updated_at")
        items.append(activity)
    for task in _timeline_rows(db, "task", "tasks", refs):
        task["timestamp"] = task.get("due_at") or task.get("updated_at")
        items.append(task)
    for note in _timeline_rows(db, "note", "notes", refs):
        note["timestamp"] = note.get("updated_at")
        items.append(note)
    if entity_type in {"lead", "account", "contact", "deal"}:
        event_rows = db.execute(
            "SELECT * FROM events WHERE entity_type = ? AND entity_id = ? ORDER BY created_at DESC LIMIT 50",
            (entity_type, entity_id),
        ).fetchall()
        for event in event_rows:
            item = row_to_dict(event)
            item["entity_type"] = "event"
            item["timestamp"] = item.get("created_at")
            items.append(item)
    for external_ref in _external_timeline_rows(db, refs):
        items.append(external_ref)
    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return {"ok": True, "entity_type": entity_type, "id": entity_id, "items": items[:100]}


def link_external_ref(db, payload: dict[str, Any]) -> dict[str, Any]:
    crm_entity_type, crm_entity_id = _crm_external_ref_target(payload)
    get_record(db, crm_entity_type, crm_entity_id)
    source_app_id = require_text(payload, "source_app_id", required=True)
    source_entity_type = require_text(payload, "source_entity_type", required=True)
    source_entity_id = require_text(payload, "source_entity_id", required=True)
    link_type = require_text(payload, "link_type", default="related") or "related"
    ref_id = require_text(payload, "id")
    now = utc_now()
    existing = None
    if ref_id:
        existing = db.execute("SELECT * FROM external_refs WHERE id = ?", (ref_id,)).fetchone()
    if existing is None:
        existing = db.execute(
            """
            SELECT * FROM external_refs
            WHERE crm_entity_type = ? AND crm_entity_id = ?
              AND source_app_id = ? AND source_entity_type = ? AND source_entity_id = ?
              AND link_type = ? AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (crm_entity_type, crm_entity_id, source_app_id, source_entity_type, source_entity_id, link_type),
        ).fetchone()
    ref_id = str(existing["id"]) if existing is not None else (ref_id or new_id("xref"))
    created_at = str(existing["created_at"]) if existing is not None else now
    db.execute(
        """
        INSERT INTO external_refs(
          id, crm_entity_type, crm_entity_id, source_app_id, source_entity_type, source_entity_id,
          link_type, title, summary, occurred_at, metadata_json, created_at, updated_at, deleted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(id) DO UPDATE SET
          crm_entity_type = excluded.crm_entity_type,
          crm_entity_id = excluded.crm_entity_id,
          source_app_id = excluded.source_app_id,
          source_entity_type = excluded.source_entity_type,
          source_entity_id = excluded.source_entity_id,
          link_type = excluded.link_type,
          title = excluded.title,
          summary = excluded.summary,
          occurred_at = excluded.occurred_at,
          metadata_json = excluded.metadata_json,
          updated_at = excluded.updated_at,
          deleted_at = NULL
        """,
        (
            ref_id,
            crm_entity_type,
            crm_entity_id,
            source_app_id,
            source_entity_type,
            source_entity_id,
            link_type,
            require_text(payload, "title") or f"{source_app_id}:{source_entity_type}:{source_entity_id}",
            require_text(payload, "summary"),
            require_text(payload, "occurred_at"),
            metadata(payload),
            created_at,
            now,
        ),
    )
    write_event(db, "external_ref.linked", crm_entity_type, crm_entity_id, {"external_ref_id": ref_id, "source_app_id": source_app_id})
    return _external_ref_from_row(db.execute("SELECT * FROM external_refs WHERE id = ?", (ref_id,)).fetchone())


def unlink_external_ref(db, payload: dict[str, Any]) -> dict[str, Any]:
    ref_id = require_text(payload, "id")
    row = None
    if ref_id:
        row = db.execute("SELECT * FROM external_refs WHERE id = ? AND deleted_at IS NULL", (ref_id,)).fetchone()
    else:
        crm_entity_type, crm_entity_id = _crm_external_ref_target(payload)
        row = db.execute(
            """
            SELECT * FROM external_refs
            WHERE crm_entity_type = ? AND crm_entity_id = ?
              AND source_app_id = ? AND source_entity_type = ? AND source_entity_id = ?
              AND link_type = ? AND deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                crm_entity_type,
                crm_entity_id,
                require_text(payload, "source_app_id", required=True),
                require_text(payload, "source_entity_type", required=True),
                require_text(payload, "source_entity_id", required=True),
                require_text(payload, "link_type", default="related") or "related",
            ),
        ).fetchone()
    if row is None:
        raise NotFoundError("external_ref was not found.")
    now = utc_now()
    db.execute("UPDATE external_refs SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, row["id"]))
    write_event(db, "external_ref.unlinked", str(row["crm_entity_type"]), str(row["crm_entity_id"]), {"external_ref_id": str(row["id"])})
    return {"ok": True, "id": str(row["id"]), "deleted_at": now}


def list_external_refs(db, payload: dict[str, Any]) -> list[dict[str, Any]]:
    where = ["deleted_at IS NULL"]
    params: list[Any] = []
    crm_entity_type = require_text(payload, "crm_entity_type") or require_text(payload, "entity_type")
    crm_entity_id = require_text(payload, "crm_entity_id") or require_text(payload, "id") or require_text(payload, "entity_id")
    if crm_entity_type:
        table_for_entity(crm_entity_type)
        where.append("crm_entity_type = ?")
        params.append(crm_entity_type)
    if crm_entity_id:
        where.append("crm_entity_id = ?")
        params.append(crm_entity_id)
    for key in ("source_app_id", "source_entity_type", "source_entity_id", "link_type"):
        value = require_text(payload, key)
        if value:
            where.append(f"{key} = ?")
            params.append(value)
    params.append(parse_limit(payload, 100))
    rows = db.execute(
        f"SELECT * FROM external_refs WHERE {' AND '.join(where)} ORDER BY COALESCE(NULLIF(occurred_at, ''), updated_at) DESC LIMIT ?",
        params,
    ).fetchall()
    return [_external_ref_from_row(row) for row in rows]


def external_timeline(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    get_record(db, entity_type, entity_id)
    refs = _timeline_refs(db, entity_type, entity_id)
    items = _external_timeline_rows(db, refs)
    return {"ok": True, "entity_type": entity_type, "id": entity_id, "items": items[:100]}


def filter_records(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    query = require_text(payload, "query")
    limit = parse_limit(payload, 100)
    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValidationError("`filters` must be an object.")
    entities = [entity_type] if entity_type != "all" else list(ENTITY_TABLES.keys())
    records: list[dict[str, Any]] = []
    for entity in entities:
        table = table_for_entity(entity)
        rows = list_rows(db, table, limit=limit, query=query)
        for record in rows:
            if _record_matches_filters(db, entity, record, filters):
                record["entity_type"] = entity
                records.append(record)
    return {"ok": True, "entity_type": entity_type, "records": records[:limit]}


def merge_records(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    if entity_type not in {"lead", "account", "contact"}:
        raise ValidationError("CRM merge supports lead, account, and contact records.", details={"entity_type": entity_type})
    target_id = require_text(payload, "target_id", required=True)
    raw_source_ids = payload.get("source_ids")
    if raw_source_ids is None:
        raw_source_ids = [require_text(payload, "source_id", required=True)]
    if not isinstance(raw_source_ids, list):
        raise ValidationError("`source_ids` must be an array of record ids.")
    source_ids = []
    for source_id in raw_source_ids:
        normalized = str(source_id or "").strip()
        if not normalized:
            continue
        if normalized == target_id:
            raise ValidationError("A record cannot be merged into itself.", details={"target_id": target_id})
        if normalized not in source_ids:
            source_ids.append(normalized)
    if not source_ids:
        raise ValidationError("At least one source record is required.")
    target = get_record(db, entity_type, target_id)
    sources = [get_record(db, entity_type, source_id) for source_id in source_ids]
    field_overrides = payload.get("field_overrides") or {}
    if not isinstance(field_overrides, dict):
        raise ValidationError("`field_overrides` must be an object.")
    merged_payload = _merge_record_payload(entity_type, target, sources, field_overrides)
    updated_target = _update_entity_record(db, entity_type, {**merged_payload, "id": target_id}) if merged_payload else target
    now = utc_now()
    reassigned_counts: dict[str, int] = {}
    for source_id in source_ids:
        _merge_record_tags(db, entity_type, source_id, target_id, now)
        _merge_custom_field_values(db, entity_type, source_id, target_id, now)
        _merge_external_refs(db, entity_type, source_id, target_id, now)
        _merge_dependents(db, entity_type, source_id, target_id, now, reassigned_counts)
        _merge_metadata_refs(db, entity_type, source_id, target_id, now, reassigned_counts)
        table = table_for_entity(entity_type)
        db.execute(f"UPDATE {table} SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, source_id))
        delete_fts(db, entity_type, source_id)
        write_event(db, "record.merged", entity_type, source_id, {"target_id": target_id, "role": "source"})
    updated_target = get_record(db, entity_type, target_id)
    reindex_record(db, entity_type, updated_target)
    write_event(db, "record.merged", entity_type, target_id, {"source_ids": source_ids, "reassigned_counts": reassigned_counts, "role": "target"})
    return {"ok": True, "entity_type": entity_type, "target": updated_target, "merged_ids": source_ids, "reassigned_counts": reassigned_counts}


def schema_config(db) -> dict[str, Any]:
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "entities": {entity_type: {"table": table, "standard_fields": _standard_fields_for_entity(entity_type)} for entity_type, table in ENTITY_TABLES.items()},
        "custom_fields": list_custom_fields(db, "all"),
        "custom_field_types": sorted(CUSTOM_FIELD_TYPES),
        "pipelines": [row_to_dict(row) for row in db.execute("SELECT * FROM pipelines ORDER BY name").fetchall()],
        "pipeline_stages": [row_to_dict(row) for row in db.execute("SELECT * FROM pipeline_stages ORDER BY pipeline_id, position").fetchall()],
        "automation_rules": list_automation_rules(db),
    }


def _standard_fields_for_entity(entity_type: str) -> list[dict[str, str]]:
    fields = {
        "lead": ["display_name", "email", "phone", "company", "domain", "source", "status", "owner_id", "summary"],
        "account": ["name", "domain", "industry", "status", "owner_id", "summary"],
        "contact": ["display_name", "email", "phone", "role", "account_id", "owner_id", "summary"],
        "deal": ["name", "account_id", "contact_id", "stage_id", "value", "currency", "probability", "close_date", "owner_id", "summary"],
        "activity": ["activity_type", "subject", "body", "account_id", "contact_id", "deal_id", "occurred_at", "due_at", "completed_at", "owner_id"],
        "task": ["title", "status", "priority", "due_at", "account_id", "contact_id", "deal_id", "owner_id", "body"],
        "note": ["body", "account_id", "contact_id", "deal_id", "owner_id"],
    }
    return [{"key": key, "label": key.replace("_", " ").title()} for key in fields.get(entity_type, [])]


def list_custom_fields(db, entity_type: str = "all") -> list[dict[str, Any]]:
    if entity_type and entity_type != "all":
        table_for_entity(entity_type)
        rows = db.execute(
            "SELECT * FROM custom_field_definitions WHERE entity_type = ? AND archived_at IS NULL ORDER BY position, lower(label)",
            (entity_type,),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM custom_field_definitions WHERE archived_at IS NULL ORDER BY entity_type, position, lower(label)").fetchall()
    return [_custom_field_from_row(row) for row in rows]


def define_custom_field(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    table_for_entity(entity_type)
    field_key = _normalize_field_key(require_text(payload, "field_key") or require_text(payload, "key", required=True))
    label = require_text(payload, "label") or field_key.replace("_", " ").title()
    field_type = require_text(payload, "field_type", default="text") or "text"
    if field_type not in CUSTOM_FIELD_TYPES:
        raise ValidationError("Unsupported custom field type.", details={"field_type": field_type, "supported": sorted(CUSTOM_FIELD_TYPES)})
    options = payload.get("options") or []
    if field_type in {"select", "multi_select"}:
        if not isinstance(options, list) or not all(isinstance(item, str) and item.strip() for item in options):
            raise ValidationError("Select custom fields require `options` as a non-empty string array.")
        options = [item.strip() for item in options]
    elif options:
        raise ValidationError("Only select custom fields can declare options.")
    default_value = _coerce_custom_field_value({"field_key": field_key, "field_type": field_type, "options": options, "required": False}, payload.get("default_value")) if "default_value" in payload else None
    now = utc_now()
    field_id = require_text(payload, "id") or new_id("field")
    db.execute(
        """
        INSERT INTO custom_field_definitions(id, entity_type, field_key, label, field_type, required, options_json, default_value_json, position, created_at, updated_at, archived_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(entity_type, field_key) DO UPDATE SET label = excluded.label, field_type = excluded.field_type,
          required = excluded.required, options_json = excluded.options_json, default_value_json = excluded.default_value_json,
          position = excluded.position, updated_at = excluded.updated_at, archived_at = NULL
        """,
        (
            field_id,
            entity_type,
            field_key,
            label,
            field_type,
            1 if bool(payload.get("required")) else 0,
            json.dumps(options, ensure_ascii=True),
            json.dumps(default_value, ensure_ascii=True),
            int(_coerce_number(payload, "position", 0)),
            now,
            now,
        ),
    )
    row = db.execute("SELECT * FROM custom_field_definitions WHERE entity_type = ? AND field_key = ?", (entity_type, field_key)).fetchone()
    write_event(db, "custom_field.defined", entity_type, field_key)
    return _custom_field_from_row(row)


def archive_custom_field(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    field_key = _normalize_field_key(require_text(payload, "field_key") or require_text(payload, "key", required=True))
    field = _custom_field_definition(db, entity_type, field_key)
    now = utc_now()
    db.execute("UPDATE custom_field_definitions SET archived_at = ?, updated_at = ? WHERE id = ?", (now, now, field["id"]))
    write_event(db, "custom_field.archived", entity_type, field_key)
    return _custom_field_from_row(db.execute("SELECT * FROM custom_field_definitions WHERE id = ?", (field["id"],)).fetchone())


def set_custom_fields(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    record = get_record(db, entity_type, entity_id)
    values = payload.get("custom_fields") or payload.get("values") or {}
    if not isinstance(values, dict):
        raise ValidationError("`custom_fields` must be an object.")
    fields = {field["field_key"]: field for field in list_custom_fields(db, entity_type)}
    unknown = sorted(str(key) for key in values if str(key) not in fields)
    if unknown:
        raise ValidationError("Unknown custom field key.", details={"entity_type": entity_type, "keys": unknown})
    now = utc_now()
    for key, raw_value in values.items():
        field = fields[str(key)]
        value = _coerce_custom_field_value(field, raw_value)
        db.execute(
            """
            INSERT INTO custom_field_values(entity_type, entity_id, field_id, value_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, entity_id, field_id) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (entity_type, entity_id, field["id"], json.dumps(value, ensure_ascii=True), now),
        )
    table = table_for_entity(entity_type)
    db.execute(f"UPDATE {table} SET updated_at = ? WHERE id = ?", (now, entity_id))
    updated = get_record(db, entity_type, entity_id)
    reindex_record(db, entity_type, updated)
    write_event(db, f"{entity_type}.custom_fields.updated", entity_type, entity_id, {"keys": sorted(values.keys())})
    return updated


def list_automation_rules(db) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM automation_rules ORDER BY updated_at DESC").fetchall()
    return [row_to_dict(row) for row in rows]


def create_automation_rule(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    rule_id = require_text(payload, "id") or new_id("auto")
    trigger_event = require_text(payload, "trigger_event", required=True)
    entity_type = view_entity_type(payload)
    conditions = payload.get("conditions") or {}
    action = payload.get("action") or {}
    if not isinstance(conditions, dict) or not isinstance(action, dict):
        raise ValidationError("Automation `conditions` and `action` must be objects.")
    db.execute(
        """
        INSERT INTO automation_rules(id, name, trigger_event, entity_type, conditions_json, action_json, approval_required, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rule_id,
            require_text(payload, "name", required=True),
            trigger_event,
            entity_type,
            json.dumps(conditions, ensure_ascii=True, sort_keys=True),
            json.dumps(action, ensure_ascii=True, sort_keys=True),
            1 if payload.get("approval_required", True) else 0,
            require_text(payload, "status", default="active") or "active",
            now,
            now,
        ),
    )
    write_event(db, "automation_rule.created", "automation_rule", rule_id)
    return row_to_dict(db.execute("SELECT * FROM automation_rules WHERE id = ?", (rule_id,)).fetchone())


def update_automation_rule(db, payload: dict[str, Any]) -> dict[str, Any]:
    rule_id = require_text(payload, "id", required=True)
    current = db.execute("SELECT * FROM automation_rules WHERE id = ?", (rule_id,)).fetchone()
    if current is None:
        raise NotFoundError(f"automation_rule `{rule_id}` was not found.")
    merged = {**row_to_dict(current), **payload}
    conditions = merged.get("conditions") or {}
    action = merged.get("action") or {}
    if not isinstance(conditions, dict) or not isinstance(action, dict):
        raise ValidationError("Automation `conditions` and `action` must be objects.")
    db.execute(
        """
        UPDATE automation_rules SET name = ?, trigger_event = ?, entity_type = ?, conditions_json = ?, action_json = ?,
          approval_required = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            require_text(merged, "name", required=True),
            require_text(merged, "trigger_event", required=True),
            view_entity_type(merged),
            json.dumps(conditions, ensure_ascii=True, sort_keys=True),
            json.dumps(action, ensure_ascii=True, sort_keys=True),
            1 if bool(merged.get("approval_required", True)) else 0,
            require_text(merged, "status", default="active") or "active",
            utc_now(),
            rule_id,
        ),
    )
    write_event(db, "automation_rule.updated", "automation_rule", rule_id)
    return row_to_dict(db.execute("SELECT * FROM automation_rules WHERE id = ?", (rule_id,)).fetchone())


def record_enrichment(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    record = get_record(db, entity_type, entity_id)
    suggestions = _enrichment_suggestions_for_record(db, entity_type, record)
    result: dict[str, Any] = {"ok": True, "entity_type": entity_type, "id": entity_id, "suggestions": suggestions}
    changes = _changes_from_enrichment(entity_type, suggestions)
    if payload.get("create_proposal") and changes:
        proposal = _create_workflow_proposal(
            db,
            "enrichment",
            entity_type,
            entity_id,
            f"Apply enrichment to {title_for_record(record)}",
            {"action": {"type": "update_record", "entity_type": entity_type, "id": entity_id, "changes": changes}, "suggestions": suggestions},
            source="crm.enrichment",
        )
        result["workflow_proposal"] = proposal
    return result


def intelligent_next_actions(db, payload: dict[str, Any]) -> list[dict[str, Any]]:
    limit = parse_limit(payload, 20)
    actions: list[dict[str, Any]] = []
    for task in list_next_actions(db, {"limit": limit}):
        score = 80 if task.get("priority") == "high" else 60
        if task.get("due_at"):
            score += 10
        actions.append({"kind": "task", "score": score, "reason": "Open CRM task", "entity_type": "task", "entity_id": task["id"], "title": task["title"], "record": task})
    actions.extend(_deal_next_action_suggestions(db))
    actions.extend(_lead_next_action_suggestions(db))
    actions.extend(_account_next_action_suggestions(db))
    actions.sort(key=lambda item: (int(item.get("score") or 0), str(item.get("title") or "")), reverse=True)
    return actions[:limit]


def propose_workflows(db, payload: dict[str, Any]) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    for action in intelligent_next_actions(db, {"limit": parse_limit(payload, 10)}):
        if action.get("kind") == "recommendation":
            created.append(
                _create_workflow_proposal(
                    db,
                    "next_action",
                    str(action["entity_type"]),
                    str(action["entity_id"]),
                    str(action["title"]),
                    {"action": action.get("action") or {}, "reason": action.get("reason"), "score": action.get("score")},
                    source="crm.next_actions",
                )
            )
    automation = run_automation_rules(db, {**payload, "limit": parse_limit(payload, 10)}) if payload.get("include_automation", True) else {"workflow_proposals": []}
    created.extend(automation.get("workflow_proposals") or [])
    return {
        "ok": True,
        "created_count": len(created),
        "workflow_proposals": created,
        "automation": {key: value for key, value in automation.items() if key not in {"workflow_proposals", "ok"}},
    }


def run_automation_rules(db, payload: dict[str, Any]) -> dict[str, Any]:
    trigger_event = require_text(payload, "trigger_event")
    requested_entity_type = require_text(payload, "entity_type")
    requested_entity_id = require_text(payload, "entity_id") or require_text(payload, "id")
    if requested_entity_type and requested_entity_type != "all":
        table_for_entity(requested_entity_type)
    if requested_entity_id and not requested_entity_type:
        raise ValidationError("`entity_type` is required when `entity_id` is provided.")
    where = ["status = 'active'"]
    params: list[Any] = []
    if trigger_event:
        where.append("trigger_event = ?")
        params.append(trigger_event)
    if requested_entity_type and requested_entity_type != "all":
        where.append("entity_type IN ('all', ?)")
        params.append(requested_entity_type)
    rules = [row_to_dict(row) for row in db.execute(f"SELECT * FROM automation_rules WHERE {' AND '.join(where)} ORDER BY updated_at DESC", params).fetchall()]
    created: list[dict[str, Any]] = []
    skipped_duplicate = 0
    skipped_invalid: list[dict[str, Any]] = []
    checked_records = 0
    limit = parse_limit(payload, 50)
    for rule in rules:
        entity_types = [requested_entity_type] if requested_entity_type and requested_entity_type != "all" else _automation_rule_entity_types(rule)
        for entity_type in entity_types:
            for record in _automation_candidate_records(db, entity_type, requested_entity_id, limit):
                checked_records += 1
                if not _automation_conditions_match(record, rule.get("conditions") if isinstance(rule.get("conditions"), dict) else {}):
                    continue
                proposal = _automation_proposal_payload(rule, entity_type, record)
                candidate = {"entity_type": entity_type, "entity_id": record["id"], "proposal": proposal}
                issues = _workflow_proposal_action_issues(db, candidate)
                if issues:
                    skipped_invalid.append({"rule_id": rule.get("id"), "entity_type": entity_type, "entity_id": record["id"], "issues": issues})
                    continue
                source = f"crm.automation:{rule['id']}"
                if _workflow_proposal_duplicate_exists(db, source, entity_type, str(record["id"]), proposal):
                    skipped_duplicate += 1
                    continue
                created.append(
                    _create_workflow_proposal(
                        db,
                        "automation_rule",
                        entity_type,
                        str(record["id"]),
                        str(rule.get("name") or "Automation proposal"),
                        proposal,
                        source=source,
                    )
                )
    return {
        "ok": True,
        "checked_rule_count": len(rules),
        "checked_record_count": checked_records,
        "created_count": len(created),
        "skipped_duplicate_count": skipped_duplicate,
        "skipped_invalid_count": len(skipped_invalid),
        "skipped_invalid": skipped_invalid[:20],
        "workflow_proposals": created,
    }


def apply_workflow_proposal(db, payload: dict[str, Any]) -> dict[str, Any]:
    proposal_id = require_text(payload, "id", required=True)
    proposal = _workflow_proposal(db, proposal_id)
    if proposal["status"] == "pending" and payload.get("approve"):
        proposal = approve_workflow_proposal(db, payload)
    if proposal["status"] != "approved":
        raise ValidationError("Workflow proposal must be approved before applying.", details={"status": proposal["status"]})
    proposal_payload = proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {}
    action = proposal_payload.get("action") if isinstance(proposal_payload.get("action"), dict) else {}
    applied_record: dict[str, Any] | None = None
    action_type = str(action.get("type") or "")
    if action_type == "create_task":
        applied_record = create_task(db, action)
    elif action_type == "update_record":
        entity_type = str(action.get("entity_type") or proposal["entity_type"])
        changes = action.get("changes") if isinstance(action.get("changes"), dict) else {}
        custom_fields = changes.pop("custom_fields", None)
        if not changes and not isinstance(custom_fields, dict):
            raise ValidationError("Workflow proposal update has no applicable changes.", details={"proposal_id": proposal_id})
        if changes:
            applied_record = _update_entity_record(db, entity_type, {**changes, "id": str(action.get("id") or proposal["entity_id"])})
        if isinstance(custom_fields, dict):
            applied_record = set_custom_fields(db, {"entity_type": entity_type, "id": str(action.get("id") or proposal["entity_id"]), "custom_fields": custom_fields})
    else:
        raise ValidationError("Unsupported workflow proposal action.", details={"type": action_type})
    now = utc_now()
    db.execute("UPDATE workflow_proposals SET status = 'applied', applied_at = ?, updated_at = ? WHERE id = ?", (now, now, proposal_id))
    write_event(db, "workflow_proposal.applied", proposal["entity_type"], proposal["entity_id"], {"proposal_id": proposal_id, "action_type": action_type})
    return {"ok": True, "workflow_proposal": _workflow_proposal(db, proposal_id), "record": applied_record}


def _update_entity_record(db, entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if entity_type == "lead":
        return update_lead(db, payload)
    if entity_type == "account":
        return update_account(db, payload)
    if entity_type == "contact":
        return update_contact(db, payload)
    if entity_type == "deal":
        return update_deal(db, payload)
    if entity_type == "task":
        return update_task(db, payload)
    if entity_type == "note":
        return update_note(db, payload)
    raise ValidationError("Bulk update supports lead, account, contact, deal, task, and note.", details={"entity_type": entity_type})


def _timeline_refs(db, entity_type: str, entity_id: str) -> dict[str, set[str]]:
    refs = {"account_id": set(), "contact_id": set(), "deal_id": set()}
    if entity_type == "lead":
        refs["lead_id"] = {entity_id}
    if entity_type == "account":
        refs["account_id"].add(entity_id)
        refs["contact_id"].update(str(row["id"]) for row in db.execute("SELECT id FROM contacts WHERE account_id = ? AND deleted_at IS NULL", (entity_id,)).fetchall())
        refs["deal_id"].update(str(row["id"]) for row in db.execute("SELECT id FROM deals WHERE account_id = ? AND deleted_at IS NULL", (entity_id,)).fetchall())
    elif entity_type == "contact":
        refs["contact_id"].add(entity_id)
        refs["deal_id"].update(str(row["id"]) for row in db.execute("SELECT id FROM deals WHERE contact_id = ? AND deleted_at IS NULL", (entity_id,)).fetchall())
        row = db.execute("SELECT account_id FROM contacts WHERE id = ?", (entity_id,)).fetchone()
        if row and row["account_id"]:
            refs["account_id"].add(str(row["account_id"]))
    elif entity_type == "deal":
        refs["deal_id"].add(entity_id)
        row = db.execute("SELECT account_id, contact_id FROM deals WHERE id = ?", (entity_id,)).fetchone()
        if row:
            if row["account_id"]:
                refs["account_id"].add(str(row["account_id"]))
            if row["contact_id"]:
                refs["contact_id"].add(str(row["contact_id"]))
    return refs


def _crm_external_ref_target(payload: dict[str, Any]) -> tuple[str, str]:
    entity_type = require_text(payload, "crm_entity_type") or require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "crm_entity_id") or require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    table_for_entity(entity_type)
    return entity_type, entity_id


def _external_ref_from_row(row) -> dict[str, Any]:
    item = row_to_dict(row)
    item["entity_type"] = "external_ref"
    item["timestamp"] = item.get("occurred_at") or item.get("updated_at")
    item["status"] = "linked" if not item.get("deleted_at") else "deleted"
    item["ref"] = {
        "app_id": item.get("source_app_id"),
        "entity_type": item.get("source_entity_type"),
        "entity_id": item.get("source_entity_id"),
        "title": item.get("title"),
        "summary": item.get("summary"),
    }
    return item


def _external_timeline_rows(db, refs: dict[str, set[str]]) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for entity_type, ids in {
        "lead": refs.get("lead_id", set()),
        "account": refs.get("account_id", set()),
        "contact": refs.get("contact_id", set()),
        "deal": refs.get("deal_id", set()),
    }.items():
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            clauses.append(f"(crm_entity_type = ? AND crm_entity_id IN ({placeholders}))")
            params.append(entity_type)
            params.extend(sorted(ids))
    if not clauses:
        return []
    rows = db.execute(
        f"""
        SELECT * FROM external_refs
        WHERE deleted_at IS NULL AND ({' OR '.join(clauses)})
        ORDER BY COALESCE(NULLIF(occurred_at, ''), updated_at) DESC
        LIMIT 100
        """,
        params,
    ).fetchall()
    return [_external_ref_from_row(row) for row in rows]


def _timeline_rows(db, entity_type: str, table: str, refs: dict[str, set[str]]) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for field, values in refs.items():
        if field not in {"account_id", "contact_id", "deal_id"}:
            continue
        if values:
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"{field} IN ({placeholders})")
            params.extend(sorted(values))
    if not clauses:
        return []
    rows = db.execute(
        f"SELECT * FROM {table} WHERE deleted_at IS NULL AND archived_at IS NULL AND ({' OR '.join(clauses)}) ORDER BY updated_at DESC LIMIT 100",
        params,
    ).fetchall()
    result = []
    for row in rows:
        item = attach_tags(db, entity_type, row_to_dict(row))
        item["entity_type"] = entity_type
        result.append(item)
    return result


def _record_matches_filters(db, entity_type: str, record: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key in ("status", "stage_id", "owner_id", "account_id", "contact_id", "deal_id"):
        expected = str(filters.get(key) or "").strip()
        if expected and str(record.get(key) or "") != expected:
            return False
    tag = str(filters.get("tag") or "").strip().lower()
    if tag:
        tags = [str(item.get("name") or "").lower() for item in record.get("tags", []) if isinstance(item, dict)]
        if tag not in tags:
            return False
    if entity_type == "deal":
        value = float(record.get("value") or 0)
        min_value = filters.get("min_value")
        max_value = filters.get("max_value")
        if min_value not in (None, "") and value < float(min_value):
            return False
        if max_value not in (None, "") and value > float(max_value):
            return False
    custom_filters = filters.get("custom_fields") if isinstance(filters.get("custom_fields"), dict) else {}
    custom_values = record.get("custom_fields") if isinstance(record.get("custom_fields"), dict) else {}
    for key, expected in custom_filters.items():
        if expected in (None, ""):
            continue
        if str(custom_values.get(str(key)) or "") != str(expected):
            return False
    return True


def _custom_field_from_row(row) -> dict[str, Any]:
    item = row_to_dict(row)
    item["required"] = bool(item.get("required"))
    return item


def _normalize_field_key(value: str) -> str:
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not key or any(char not in FIELD_KEY_CHARS for char in key):
        raise ValidationError("Custom field key must contain only lowercase letters, numbers, and underscores.", details={"field_key": value})
    return key


def _custom_field_definition(db, entity_type: str, field_key: str) -> dict[str, Any]:
    table_for_entity(entity_type)
    row = db.execute(
        "SELECT * FROM custom_field_definitions WHERE entity_type = ? AND field_key = ? AND archived_at IS NULL",
        (entity_type, field_key),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"custom_field `{entity_type}.{field_key}` was not found.")
    return _custom_field_from_row(row)


def _coerce_custom_field_value(field: dict[str, Any], raw_value: Any) -> Any:
    field_type = str(field.get("field_type") or "text")
    required = bool(field.get("required"))
    if raw_value in (None, ""):
        if required:
            raise ValidationError("Required custom field cannot be empty.", details={"field_key": field.get("field_key")})
        return None
    if field_type in {"text", "url", "email", "date"}:
        value = str(raw_value).strip()
        if field_type == "email" and value and "@" not in value:
            raise ValidationError("Email custom field must contain an email-like value.", details={"field_key": field.get("field_key")})
        return value
    if field_type == "number":
        try:
            number = float(raw_value)
        except (TypeError, ValueError) as error:
            raise ValidationError("Number custom field must be numeric.", details={"field_key": field.get("field_key")}) from error
        if not math.isfinite(number):
            raise ValidationError("Number custom field must be finite.", details={"field_key": field.get("field_key")})
        return number
    if field_type == "boolean":
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str) and raw_value.lower() in {"true", "1", "yes", "y"}:
            return True
        if isinstance(raw_value, str) and raw_value.lower() in {"false", "0", "no", "n"}:
            return False
        raise ValidationError("Boolean custom field must be true or false.", details={"field_key": field.get("field_key")})
    options = field.get("options") if isinstance(field.get("options"), list) else []
    if field_type == "select":
        value = str(raw_value).strip()
        if value not in options:
            raise ValidationError("Select custom field value is not in options.", details={"field_key": field.get("field_key"), "options": options})
        return value
    if field_type == "multi_select":
        if not isinstance(raw_value, list):
            raise ValidationError("Multi-select custom field value must be an array.", details={"field_key": field.get("field_key")})
        values = [str(item).strip() for item in raw_value if str(item).strip()]
        unknown = sorted(set(values) - set(options))
        if unknown:
            raise ValidationError("Multi-select custom field values are not in options.", details={"field_key": field.get("field_key"), "unknown": unknown})
        return values
    raise ValidationError("Unsupported custom field type.", details={"field_type": field_type})


def _enrichment_suggestions_for_record(db, entity_type: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    email = str(record.get("email") or "").strip().lower()
    if entity_type == "lead" and email and "@" in email and not record.get("domain"):
        suggestions.append({"field": "domain", "value": email.rsplit("@", 1)[1], "confidence": 0.82, "reason": "Derived from email domain."})
    if entity_type in {"lead", "contact"} and not record.get("display_name"):
        fallback = " ".join(part for part in [record.get("first_name"), record.get("last_name")] if part) or email
        if fallback:
            suggestions.append({"field": "display_name", "value": fallback, "confidence": 0.72, "reason": "Derived from name or email."})
    if entity_type == "contact" and not record.get("account_id") and email and "@" in email:
        domain = email.rsplit("@", 1)[1]
        match = db.execute("SELECT * FROM accounts WHERE lower(domain) = ? AND deleted_at IS NULL AND archived_at IS NULL ORDER BY updated_at DESC LIMIT 1", (domain,)).fetchone()
        if match:
            account = row_to_dict(match)
            suggestions.append({"field": "account_id", "value": account["id"], "confidence": 0.86, "reason": f"Matched account domain {domain}."})
    if entity_type == "deal" and not record.get("close_date") and float(record.get("value") or 0) > 0:
        suggestions.append({"field": "next_action", "value": "Set close date", "confidence": 0.64, "reason": "Valued deal has no close date."})
    custom_fields = record.get("custom_fields") if isinstance(record.get("custom_fields"), dict) else {}
    for field in list_custom_fields(db, entity_type):
        if field.get("required") and custom_fields.get(str(field["field_key"])) in (None, "") and field.get("default_value") not in (None, ""):
            suggestions.append({"field": f"custom_fields.{field['field_key']}", "value": field.get("default_value"), "confidence": 0.6, "reason": "Required custom field is empty."})
    return suggestions


def _changes_from_enrichment(entity_type: str, suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    custom_fields: dict[str, Any] = {}
    standard_fields = {field["key"] for field in _standard_fields_for_entity(entity_type)}
    for suggestion in suggestions:
        field = str(suggestion.get("field") or "")
        if field == "next_action":
            continue
        if field.startswith("custom_fields."):
            value = suggestion.get("value")
            if value not in (None, ""):
                custom_fields[field.split(".", 1)[1]] = value
        elif field in standard_fields:
            changes[field] = suggestion.get("value")
    if custom_fields:
        changes["custom_fields"] = custom_fields
    return changes


def _deal_next_action_suggestions(db) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM deals
        WHERE deleted_at IS NULL AND archived_at IS NULL
          AND lower(stage) NOT IN ('won', 'lost')
          AND value > 0
          AND NOT EXISTS (SELECT 1 FROM tasks WHERE tasks.deal_id = deals.id AND tasks.status = 'open' AND tasks.deleted_at IS NULL AND tasks.archived_at IS NULL)
        ORDER BY value DESC, updated_at ASC
        LIMIT 20
        """
    ).fetchall()
    return [
        {
            "kind": "recommendation",
            "score": 75 + min(20, int(float(row["value"] or 0) / 10000)),
            "reason": "Open valued deal has no open follow-up task.",
            "entity_type": "deal",
            "entity_id": row["id"],
            "title": f"Schedule follow-up for {row['name']}",
            "action": {"type": "create_task", "title": f"Follow up on {row['name']}", "deal_id": row["id"], "account_id": row["account_id"], "contact_id": row["contact_id"], "priority": "high"},
        }
        for row in rows
    ]


def _lead_next_action_suggestions(db) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM leads
        WHERE deleted_at IS NULL AND archived_at IS NULL AND converted_at = '' AND status IN ('new', 'qualified')
          AND NOT EXISTS (SELECT 1 FROM tasks WHERE tasks.metadata_json LIKE '%' || leads.id || '%' AND tasks.status = 'open' AND tasks.deleted_at IS NULL)
        ORDER BY updated_at ASC
        LIMIT 20
        """
    ).fetchall()
    suggestions = []
    for row in rows:
        title = str(row["display_name"])
        suggestions.append(
            {
                "kind": "recommendation",
                "score": 68 if row["status"] == "qualified" else 58,
                "reason": "Unconverted lead needs qualification or conversion follow-up.",
                "entity_type": "lead",
                "entity_id": row["id"],
                "title": f"Qualify lead {title}",
                "action": {"type": "create_task", "title": f"Qualify lead {title}", "priority": "normal", "metadata": {"lead_id": row["id"]}},
            }
        )
    return suggestions


def _account_next_action_suggestions(db) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT * FROM accounts
        WHERE deleted_at IS NULL AND archived_at IS NULL
          AND status IN ('prospect', 'customer')
          AND NOT EXISTS (SELECT 1 FROM tasks WHERE tasks.account_id = accounts.id AND tasks.status = 'open' AND tasks.deleted_at IS NULL AND tasks.archived_at IS NULL)
        ORDER BY updated_at ASC
        LIMIT 20
        """
    ).fetchall()
    return [
        {
            "kind": "recommendation",
            "score": 52,
            "reason": "Active account has no open next action.",
            "entity_type": "account",
            "entity_id": row["id"],
            "title": f"Create next step for {row['name']}",
            "action": {"type": "create_task", "title": f"Define next step for {row['name']}", "account_id": row["id"], "priority": "normal"},
        }
        for row in rows
    ]


def _automation_rule_entity_types(rule: dict[str, Any]) -> list[str]:
    entity_type = str(rule.get("entity_type") or "all")
    if entity_type == "all":
        return ["lead", "account", "contact", "deal"]
    return [entity_type] if entity_type in ENTITY_TABLES else []


def _automation_candidate_records(db, entity_type: str, entity_id: str, limit: int) -> list[dict[str, Any]]:
    table = table_for_entity(entity_type)
    if entity_id:
        return [get_record(db, entity_type, entity_id)]
    rows = db.execute(
        f"SELECT * FROM {table} WHERE deleted_at IS NULL AND archived_at IS NULL ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    records = []
    for row in rows:
        record = row_to_dict(row)
        record["entity_type"] = entity_type
        records.append(attach_tags(db, entity_type, record))
    return records


def _automation_conditions_match(record: dict[str, Any], conditions: dict[str, Any]) -> bool:
    for field, expected in conditions.items():
        actual = _automation_record_value(record, str(field))
        if isinstance(expected, dict):
            if "equals" in expected and str(actual or "") != str(expected.get("equals") or ""):
                return False
            if "not" in expected and str(actual or "") == str(expected.get("not") or ""):
                return False
            if "in" in expected:
                options = expected.get("in")
                if not isinstance(options, list) or str(actual or "") not in {str(item) for item in options}:
                    return False
            if "min" in expected and _coerce_optional_float(actual) < _coerce_optional_float(expected.get("min")):
                return False
            if "max" in expected and _coerce_optional_float(actual) > _coerce_optional_float(expected.get("max")):
                return False
            if "empty" in expected and bool(expected.get("empty")) != (actual in (None, "")):
                return False
            if "exists" in expected and bool(expected.get("exists")) != (actual not in (None, "")):
                return False
        elif str(actual or "") != str(expected or ""):
            return False
    return True


def _automation_record_value(record: dict[str, Any], field: str) -> Any:
    if field.startswith("custom_fields."):
        custom_fields = record.get("custom_fields") if isinstance(record.get("custom_fields"), dict) else {}
        return custom_fields.get(field.split(".", 1)[1])
    return record.get(field)


def _coerce_optional_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _automation_proposal_payload(rule: dict[str, Any], entity_type: str, record: dict[str, Any]) -> dict[str, Any]:
    action = dict(rule.get("action") if isinstance(rule.get("action"), dict) else {})
    action_type = str(action.get("type") or "")
    if action_type == "update_record":
        action.setdefault("entity_type", entity_type)
        action.setdefault("id", record["id"])
    elif action_type == "create_task":
        if entity_type in {"account", "contact", "deal"}:
            action.setdefault(f"{entity_type}_id", record["id"])
        else:
            metadata_value = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
            metadata_value = {**metadata_value, "lead_id": record["id"]}
            action["metadata"] = metadata_value
        if not action.get("title"):
            action["title"] = f"Follow up on {title_for_record(record)}"
    return {"rule_id": rule.get("id"), "trigger_event": rule.get("trigger_event"), "action": action}


def _merge_record_payload(entity_type: str, target: dict[str, Any], sources: list[dict[str, Any]], overrides: dict[str, Any]) -> dict[str, Any]:
    fields_by_entity = {
        "lead": ("first_name", "last_name", "display_name", "email", "phone", "company", "domain", "source", "status", "owner_id", "summary", "account_id", "contact_id", "deal_id"),
        "account": ("name", "domain", "industry", "status", "owner_id", "summary"),
        "contact": ("account_id", "first_name", "last_name", "display_name", "email", "phone", "role", "owner_id", "summary"),
    }
    merged: dict[str, Any] = {}
    for field in fields_by_entity[entity_type]:
        if target.get(field) not in (None, ""):
            continue
        for source in sources:
            if source.get(field) not in (None, ""):
                merged[field] = source.get(field)
                break
    metadata_values = dict(target.get("metadata") if isinstance(target.get("metadata"), dict) else {})
    for source in sources:
        source_metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        for key, value in source_metadata.items():
            metadata_values.setdefault(key, value)
    if metadata_values != (target.get("metadata") if isinstance(target.get("metadata"), dict) else {}):
        merged["metadata"] = metadata_values
    for field, value in overrides.items():
        if field in fields_by_entity[entity_type] or field == "metadata":
            merged[str(field)] = value
    return merged


def _merge_record_tags(db, entity_type: str, source_id: str, target_id: str, now: str) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO record_tags(record_type, record_id, tag_id, created_at)
        SELECT record_type, ?, tag_id, ? FROM record_tags
        WHERE record_type = ? AND record_id = ?
        """,
        (target_id, now, entity_type, source_id),
    )
    db.execute("DELETE FROM record_tags WHERE record_type = ? AND record_id = ?", (entity_type, source_id))


def _merge_custom_field_values(db, entity_type: str, source_id: str, target_id: str, now: str) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO custom_field_values(entity_type, entity_id, field_id, value_json, updated_at)
        SELECT entity_type, ?, field_id, value_json, ? FROM custom_field_values
        WHERE entity_type = ? AND entity_id = ?
        """,
        (target_id, now, entity_type, source_id),
    )
    db.execute("DELETE FROM custom_field_values WHERE entity_type = ? AND entity_id = ?", (entity_type, source_id))


def _merge_external_refs(db, entity_type: str, source_id: str, target_id: str, now: str) -> None:
    db.execute(
        "UPDATE external_refs SET crm_entity_id = ?, updated_at = ? WHERE crm_entity_type = ? AND crm_entity_id = ? AND deleted_at IS NULL",
        (target_id, now, entity_type, source_id),
    )


def _merge_dependents(db, entity_type: str, source_id: str, target_id: str, now: str, counts: dict[str, int]) -> None:
    dependent_specs = {
        "account": (("contacts", "account_id"), ("deals", "account_id"), ("activities", "account_id"), ("tasks", "account_id"), ("notes", "account_id")),
        "contact": (("deals", "contact_id"), ("activities", "contact_id"), ("tasks", "contact_id"), ("notes", "contact_id")),
    }
    for table, field in dependent_specs.get(entity_type, ()):
        cursor = db.execute(
            f"UPDATE {table} SET {field} = ?, updated_at = ? WHERE {field} = ? AND deleted_at IS NULL",
            (target_id, now, source_id),
        )
        counts[f"{table}.{field}"] = counts.get(f"{table}.{field}", 0) + int(cursor.rowcount if cursor.rowcount is not None else 0)


def _merge_metadata_refs(db, entity_type: str, source_id: str, target_id: str, now: str, counts: dict[str, int]) -> None:
    metadata_key = f"{entity_type}_id"
    for table in ("activities", "tasks", "notes"):
        rows = db.execute(f"SELECT id, metadata_json FROM {table} WHERE deleted_at IS NULL AND metadata_json LIKE ?", (f"%{source_id}%",)).fetchall()
        changed = 0
        for row in rows:
            metadata_value = json.loads(str(row["metadata_json"] or "{}"))
            if not isinstance(metadata_value, dict):
                continue
            did_change = False
            if str(metadata_value.get(metadata_key) or "") == source_id:
                metadata_value[metadata_key] = target_id
                did_change = True
            nested = metadata_value.get("crm_ref")
            if isinstance(nested, dict) and nested.get("entity_type") == entity_type and nested.get("entity_id") == source_id:
                nested["entity_id"] = target_id
                did_change = True
            if did_change:
                db.execute(f"UPDATE {table} SET metadata_json = ?, updated_at = ? WHERE id = ?", (json.dumps(metadata_value, ensure_ascii=True, sort_keys=True), now, row["id"]))
                changed += 1
        if changed:
            counts[f"{table}.metadata_json"] = counts.get(f"{table}.metadata_json", 0) + changed


def summarize_account(db, account_id: str) -> dict[str, Any]:
    account = get_record(db, "account", account_id)
    contacts = [row_to_dict(row) for row in db.execute("SELECT * FROM contacts WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    deals = [row_to_dict(row) for row in db.execute("SELECT * FROM deals WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    activities = [row_to_dict(row) for row in db.execute("SELECT * FROM activities WHERE account_id = ? AND deleted_at IS NULL ORDER BY occurred_at DESC LIMIT 10", (account_id,)).fetchall()]
    tasks = [row_to_dict(row) for row in db.execute("SELECT * FROM tasks WHERE account_id = ? AND deleted_at IS NULL ORDER BY due_at ASC, updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    notes = [row_to_dict(row) for row in db.execute("SELECT * FROM notes WHERE account_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10", (account_id,)).fetchall()]
    return {"account": account, "contacts": contacts, "deals": deals, "activities": activities, "tasks": tasks, "notes": notes}


def account_brief(db, account_id: str) -> dict[str, Any]:
    summary = summarize_account(db, account_id)
    account = summary["account"]
    open_deals = [deal for deal in summary["deals"] if str(deal.get("stage") or "").lower() not in {"won", "lost"}]
    open_tasks = [task for task in summary["tasks"] if task.get("status") == "open"]
    next_actions = [action for action in intelligent_next_actions(db, {"limit": 20}) if action.get("entity_type") in {"account", "deal"} and (action.get("entity_id") == account_id or _action_belongs_to_account(db, action, account_id))]
    total_pipeline = sum(float(deal.get("value") or 0) for deal in open_deals)
    risks: list[str] = []
    if open_deals and not open_tasks:
        risks.append("Open pipeline exists without an open account task.")
    if not summary["contacts"]:
        risks.append("No contacts are linked to this account.")
    if any(not deal.get("close_date") for deal in open_deals):
        risks.append("At least one open deal has no close date.")
    opportunities: list[str] = []
    if total_pipeline:
        opportunities.append(f"Open pipeline value: {account.get('currency', 'EUR')} {total_pipeline:,.0f}.")
    if summary["contacts"]:
        opportunities.append(f"{len(summary['contacts'])} linked contact(s) available for outreach.")
    brief_lines = [
        f"{account['name']} is a {account.get('status') or 'prospect'} account.",
        f"Linked contacts: {len(summary['contacts'])}. Open deals: {len(open_deals)}. Open tasks: {len(open_tasks)}.",
    ]
    if account.get("summary"):
        brief_lines.append(str(account["summary"]))
    return {
        "ok": True,
        "account": account,
        "brief": "\n".join(brief_lines),
        "metrics": {"contacts": len(summary["contacts"]), "open_deals": len(open_deals), "open_tasks": len(open_tasks), "open_pipeline_value": total_pipeline},
        "risks": risks,
        "opportunities": opportunities,
        "next_actions": next_actions[:5],
        "source": summary,
    }


def _action_belongs_to_account(db, action: dict[str, Any], account_id: str) -> bool:
    if action.get("entity_type") == "deal":
        row = db.execute("SELECT account_id FROM deals WHERE id = ?", (str(action.get("entity_id") or ""),)).fetchone()
        return bool(row and row["account_id"] == account_id)
    return False


def import_commit(db, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_import_payload(payload)
    if _looks_like_export_payload(payload):
        return _import_export_payload(db, payload)
    entity_type = require_text(payload, "entity_type", default="contact") or "contact"
    rows = _read_import_rows(payload)
    errors = _validate_import_rows(entity_type, rows)
    if errors:
        return {"ok": False, "entity_type": entity_type, "created_count": 0, "records": [], "errors": errors}
    created: list[dict[str, Any]] = []
    for row in rows:
        if entity_type == "lead":
            created.append(create_lead(db, row))
        elif entity_type == "account":
            created.append(create_account(db, row))
        elif entity_type == "contact":
            created.append(create_contact(db, row))
        elif entity_type == "deal":
            created.append(create_deal(db, row))
        elif entity_type == "activity":
            created.append(log_activity(db, row))
        elif entity_type == "task":
            created.append(create_task(db, row))
        elif entity_type == "note":
            created.append(create_note(db, row))
        else:
            raise ValidationError("Imports support lead, account, contact, deal, activity, task, and note.", details={"entity_type": entity_type})
    return {"ok": True, "entity_type": entity_type, "created_count": len(created), "records": created, "errors": []}


def _import_export_payload(db, payload: dict[str, Any]) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    for row in payload.get("custom_field_definitions") or []:
        if not isinstance(row, dict):
            raise ValidationError("`custom_field_definitions` must contain objects.")
        record, was_created = _upsert_custom_field_definition_export(db, row)
        (created if was_created else updated).append(record)
    for table in EXPORT_ENTITY_ORDER:
        rows = payload.get(table) or []
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValidationError(f"`{table}` must be an array of objects.")
        entity_type = TABLE_ENTITY_TYPES[table]
        for row in rows:
            record, was_created = _upsert_export_row(db, entity_type, row)
            if was_created:
                created.append(record)
            else:
                updated.append(record)
    for row in payload.get("custom_field_values") or []:
        if not isinstance(row, dict):
            raise ValidationError("`custom_field_values` must contain objects.")
        record, was_created = _upsert_custom_field_value_export(db, row)
        (created if was_created else updated).append(record)
    for row in payload.get("external_refs") or []:
        if not isinstance(row, dict):
            raise ValidationError("`external_refs` must contain objects.")
        record, was_created = _upsert_external_ref_export(db, row)
        (created if was_created else updated).append(record)
    for row in payload.get("automation_rules") or []:
        if not isinstance(row, dict):
            raise ValidationError("`automation_rules` must contain objects.")
        record, was_created = _upsert_automation_rule_export(db, row)
        (created if was_created else updated).append(record)
    for row in payload.get("workflow_proposals") or []:
        if not isinstance(row, dict):
            raise ValidationError("`workflow_proposals` must contain objects.")
        record, was_created = _upsert_workflow_proposal_export(db, row)
        (created if was_created else updated).append(record)
    return {"ok": True, "format": "crm_export", "created_count": len(created), "updated_count": len(updated), "records": created + updated}


def _upsert_export_row(db, entity_type: str, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    record_id = require_text(row, "id", required=True)
    state = record_exists(db, entity_type, record_id)
    _validate_export_row_relationships(db, entity_type, row)
    return (_write_export_row(db, entity_type, row), not state)


def _write_export_row(db, entity_type: str, row: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    created_at = require_text(row, "created_at") or now
    updated_at = require_text(row, "updated_at") or now
    archived_at = require_text(row, "archived_at") or None
    deleted_at = require_text(row, "deleted_at") or None
    metadata_json = json.dumps(row.get("metadata") if isinstance(row.get("metadata"), dict) else {}, ensure_ascii=True, sort_keys=True)
    common_lifecycle = {"created_at": created_at, "updated_at": updated_at, "archived_at": archived_at, "deleted_at": deleted_at}

    if entity_type == "account":
        values = {
            "id": require_text(row, "id", required=True),
            "name": require_text(row, "name", required=True),
            "domain": require_text(row, "domain"),
            "industry": require_text(row, "industry"),
            "status": require_text(row, "status", default="prospect") or "prospect",
            "owner_id": require_text(row, "owner_id"),
            "summary": require_text(row, "summary"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "accounts", values)
    elif entity_type == "lead":
        first_name = require_text(row, "first_name")
        last_name = require_text(row, "last_name")
        display_name = require_text(row, "display_name") or " ".join(part for part in [first_name, last_name] if part) or require_text(row, "email", required=True)
        values = {
            "id": require_text(row, "id", required=True),
            "first_name": first_name,
            "last_name": last_name,
            "display_name": display_name,
            "email": require_text(row, "email"),
            "phone": require_text(row, "phone"),
            "company": require_text(row, "company"),
            "domain": require_text(row, "domain"),
            "source": require_text(row, "source"),
            "status": require_text(row, "status", default="new") or "new",
            "owner_id": require_text(row, "owner_id"),
            "summary": require_text(row, "summary"),
            "metadata_json": metadata_json,
            "converted_at": require_text(row, "converted_at"),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "deal_id": require_text(row, "deal_id"),
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "leads", values)
    elif entity_type == "contact":
        first_name = require_text(row, "first_name")
        last_name = require_text(row, "last_name")
        display_name = require_text(row, "display_name") or " ".join(part for part in [first_name, last_name] if part) or require_text(row, "email", required=True)
        values = {
            "id": require_text(row, "id", required=True),
            "account_id": require_text(row, "account_id"),
            "first_name": first_name,
            "last_name": last_name,
            "display_name": display_name,
            "email": require_text(row, "email"),
            "phone": require_text(row, "phone"),
            "role": require_text(row, "role"),
            "owner_id": require_text(row, "owner_id"),
            "summary": require_text(row, "summary"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "contacts", values)
    elif entity_type == "deal":
        pipeline_id = require_text(row, "pipeline_id", default="pipeline_default") or "pipeline_default"
        _require_pipeline(db, pipeline_id)
        stage_id = require_text(row, "stage_id", default=require_text(row, "stage", default="lead")) or "lead"
        values = {
            "id": require_text(row, "id", required=True),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "pipeline_id": pipeline_id,
            "stage_id": stage_id,
            "name": require_text(row, "name", required=True),
            "stage": _stage_name(db, stage_id, pipeline_id),
            "value": _coerce_number(row, "value", 0),
            "currency": require_text(row, "currency", default="EUR") or "EUR",
            "probability": _coerce_number(row, "probability", _stage_probability(db, stage_id, pipeline_id)),
            "close_date": require_text(row, "close_date"),
            "owner_id": require_text(row, "owner_id"),
            "summary": require_text(row, "summary"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "deals", values)
    elif entity_type == "activity":
        values = {
            "id": require_text(row, "id", required=True),
            "activity_type": require_text(row, "activity_type", default="note") or "note",
            "subject": require_text(row, "subject", required=True),
            "body": require_text(row, "body"),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "deal_id": require_text(row, "deal_id"),
            "occurred_at": require_text(row, "occurred_at", default=now) or now,
            "due_at": require_text(row, "due_at"),
            "completed_at": require_text(row, "completed_at"),
            "owner_id": require_text(row, "owner_id"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "activities", values)
    elif entity_type == "task":
        values = {
            "id": require_text(row, "id", required=True),
            "title": require_text(row, "title", required=True),
            "status": require_text(row, "status", default="open") or "open",
            "priority": require_text(row, "priority", default="normal") or "normal",
            "due_at": require_text(row, "due_at"),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "deal_id": require_text(row, "deal_id"),
            "owner_id": require_text(row, "owner_id"),
            "body": require_text(row, "body"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "tasks", values)
    elif entity_type == "note":
        values = {
            "id": require_text(row, "id", required=True),
            "body": require_text(row, "body", required=True),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "deal_id": require_text(row, "deal_id"),
            "owner_id": require_text(row, "owner_id"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "notes", values)
    else:
        raise ValidationError("Unsupported entity_type.", details={"entity_type": entity_type})

    if record.get("deleted_at") or record.get("archived_at"):
        delete_fts(db, entity_type, str(record["id"]))
    else:
        reindex_record(db, entity_type, record)
    write_event(db, f"{entity_type}.imported", entity_type, str(record["id"]))
    return record


def _upsert_export_table_row(db, table: str, values: dict[str, Any]) -> dict[str, Any]:
    columns = list(values.keys())
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "id")
    db.execute(
        f"""
        INSERT INTO {table}({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {updates}
        """,
        tuple(values[column] for column in columns),
    )
    entity_type = TABLE_ENTITY_TYPES[table]
    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (values["id"],)).fetchone()
    record = row_to_dict(row)
    record["entity_type"] = entity_type
    return attach_tags(db, entity_type, record)


def _validate_export_row_relationships(db, entity_type: str, row: dict[str, Any]) -> None:
    fields_by_entity = {
        "contact": ("account_id",),
        "deal": ("account_id", "contact_id"),
        "activity": ("account_id", "contact_id", "deal_id"),
        "task": ("account_id", "contact_id", "deal_id"),
        "note": ("account_id", "contact_id", "deal_id"),
    }
    fields = fields_by_entity.get(entity_type, ())
    if not fields:
        return
    row_is_active = not require_text(row, "archived_at") and not require_text(row, "deleted_at")
    mapping = {"account_id": "account", "contact_id": "contact", "deal_id": "deal"}
    for field in fields:
        entity_id = require_text(row, field)
        if not entity_id:
            continue
        state = record_exists(db, mapping[field], entity_id)
        if row_is_active and state != "active":
            raise ValidationError("Active CRM records cannot link to inactive related records.", details={"field": field, "id": entity_id, "state": state or "missing"})
        if not row_is_active and state in {"", "deleted"}:
            raise ValidationError("Related CRM record was not found.", details={"field": field, "id": entity_id, "state": state or "missing"})


def _upsert_custom_field_definition_export(db, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    field_id = require_text(row, "id") or new_id("field")
    entity_type = require_text(row, "entity_type", required=True)
    field_key = _normalize_field_key(require_text(row, "field_key", required=True))
    exists = db.execute("SELECT 1 FROM custom_field_definitions WHERE id = ? OR (entity_type = ? AND field_key = ?)", (field_id, entity_type, field_key)).fetchone() is not None
    db.execute(
        """
        INSERT INTO custom_field_definitions(id, entity_type, field_key, label, field_type, required, options_json, default_value_json, position, created_at, updated_at, archived_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, field_key) DO UPDATE SET label = excluded.label, field_type = excluded.field_type,
          required = excluded.required, options_json = excluded.options_json, default_value_json = excluded.default_value_json,
          position = excluded.position, updated_at = excluded.updated_at, archived_at = excluded.archived_at
        """,
        (
            field_id,
            entity_type,
            field_key,
            require_text(row, "label") or field_key,
            require_text(row, "field_type", default="text") or "text",
            1 if bool(row.get("required")) else 0,
            json.dumps(row.get("options") if isinstance(row.get("options"), list) else [], ensure_ascii=True),
            json.dumps(row.get("default_value"), ensure_ascii=True),
            int(_coerce_number(row, "position", 0)),
            require_text(row, "created_at") or utc_now(),
            require_text(row, "updated_at") or utc_now(),
            require_text(row, "archived_at") or None,
        ),
    )
    return (_custom_field_from_row(db.execute("SELECT * FROM custom_field_definitions WHERE entity_type = ? AND field_key = ?", (entity_type, field_key)).fetchone()), not exists)


def _upsert_custom_field_value_export(db, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    entity_type = require_text(row, "entity_type", required=True)
    entity_id = require_text(row, "entity_id", required=True)
    field_id = require_text(row, "field_id", required=True)
    exists = db.execute("SELECT 1 FROM custom_field_values WHERE entity_type = ? AND entity_id = ? AND field_id = ?", (entity_type, entity_id, field_id)).fetchone() is not None
    field_exists = db.execute("SELECT 1 FROM custom_field_definitions WHERE id = ? AND entity_type = ?", (field_id, entity_type)).fetchone() is not None
    if not field_exists:
        raise ValidationError("Custom field value references an unknown field definition.", details={"entity_type": entity_type, "entity_id": entity_id, "field_id": field_id})
    state = record_exists(db, entity_type, entity_id)
    if state in {"", "deleted"}:
        raise ValidationError("Custom field value references a missing CRM record.", details={"entity_type": entity_type, "entity_id": entity_id, "state": state or "missing"})
    db.execute(
        """
        INSERT INTO custom_field_values(entity_type, entity_id, field_id, value_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id, field_id) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
        """,
        (entity_type, entity_id, field_id, json.dumps(row.get("value"), ensure_ascii=True), require_text(row, "updated_at") or utc_now()),
    )
    if state == "active":
        updated = get_record(db, entity_type, entity_id)
        reindex_record(db, entity_type, updated)
    return ({"entity_type": entity_type, "entity_id": entity_id, "field_id": field_id, "value": row.get("value")}, not exists)


def _upsert_external_ref_export(db, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    ref_id = require_text(row, "id") or new_id("xref")
    crm_entity_type = require_text(row, "crm_entity_type", required=True)
    crm_entity_id = require_text(row, "crm_entity_id", required=True)
    state = record_exists(db, crm_entity_type, crm_entity_id)
    if state in {"", "deleted"}:
        raise ValidationError("External ref references a missing CRM record.", details={"crm_entity_type": crm_entity_type, "crm_entity_id": crm_entity_id, "state": state or "missing"})
    for key in ("source_app_id", "source_entity_type", "source_entity_id"):
        require_text(row, key, required=True)
    exists = db.execute("SELECT 1 FROM external_refs WHERE id = ?", (ref_id,)).fetchone() is not None
    now = utc_now()
    db.execute(
        """
        INSERT INTO external_refs(
          id, crm_entity_type, crm_entity_id, source_app_id, source_entity_type, source_entity_id,
          link_type, title, summary, occurred_at, metadata_json, created_at, updated_at, deleted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          crm_entity_type = excluded.crm_entity_type,
          crm_entity_id = excluded.crm_entity_id,
          source_app_id = excluded.source_app_id,
          source_entity_type = excluded.source_entity_type,
          source_entity_id = excluded.source_entity_id,
          link_type = excluded.link_type,
          title = excluded.title,
          summary = excluded.summary,
          occurred_at = excluded.occurred_at,
          metadata_json = excluded.metadata_json,
          updated_at = excluded.updated_at,
          deleted_at = excluded.deleted_at
        """,
        (
            ref_id,
            crm_entity_type,
            crm_entity_id,
            require_text(row, "source_app_id", required=True),
            require_text(row, "source_entity_type", required=True),
            require_text(row, "source_entity_id", required=True),
            require_text(row, "link_type", default="related") or "related",
            require_text(row, "title"),
            require_text(row, "summary"),
            require_text(row, "occurred_at"),
            json.dumps(row.get("metadata") if isinstance(row.get("metadata"), dict) else {}, ensure_ascii=True, sort_keys=True),
            require_text(row, "created_at") or now,
            require_text(row, "updated_at") or now,
            require_text(row, "deleted_at") or None,
        ),
    )
    return (_external_ref_from_row(db.execute("SELECT * FROM external_refs WHERE id = ?", (ref_id,)).fetchone()), not exists)


def _upsert_automation_rule_export(db, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    rule_id = require_text(row, "id") or new_id("auto")
    exists = db.execute("SELECT 1 FROM automation_rules WHERE id = ?", (rule_id,)).fetchone() is not None
    db.execute(
        """
        INSERT INTO automation_rules(id, name, trigger_event, entity_type, conditions_json, action_json, approval_required, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET name = excluded.name, trigger_event = excluded.trigger_event, entity_type = excluded.entity_type,
          conditions_json = excluded.conditions_json, action_json = excluded.action_json, approval_required = excluded.approval_required,
          status = excluded.status, updated_at = excluded.updated_at
        """,
        (
            rule_id,
            require_text(row, "name", required=True),
            require_text(row, "trigger_event", required=True),
            require_text(row, "entity_type", default="all") or "all",
            json.dumps(row.get("conditions") if isinstance(row.get("conditions"), dict) else {}, ensure_ascii=True, sort_keys=True),
            json.dumps(row.get("action") if isinstance(row.get("action"), dict) else {}, ensure_ascii=True, sort_keys=True),
            1 if bool(row.get("approval_required", True)) else 0,
            require_text(row, "status", default="active") or "active",
            require_text(row, "created_at") or utc_now(),
            require_text(row, "updated_at") or utc_now(),
        ),
    )
    return (row_to_dict(db.execute("SELECT * FROM automation_rules WHERE id = ?", (rule_id,)).fetchone()), not exists)


def _upsert_workflow_proposal_export(db, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    proposal_id = require_text(row, "id") or new_id("wf")
    exists = db.execute("SELECT 1 FROM workflow_proposals WHERE id = ?", (proposal_id,)).fetchone() is not None
    db.execute(
        """
        INSERT INTO workflow_proposals(id, proposal_type, status, entity_type, entity_id, title, proposal_json, source, created_at, updated_at, approved_at, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET proposal_type = excluded.proposal_type, status = excluded.status, entity_type = excluded.entity_type,
          entity_id = excluded.entity_id, title = excluded.title, proposal_json = excluded.proposal_json, source = excluded.source,
          updated_at = excluded.updated_at, approved_at = excluded.approved_at, applied_at = excluded.applied_at
        """,
        (
            proposal_id,
            require_text(row, "proposal_type", default="next_action") or "next_action",
            require_text(row, "status", default="pending") or "pending",
            require_text(row, "entity_type", required=True),
            require_text(row, "entity_id", required=True),
            require_text(row, "title", required=True),
            json.dumps(row.get("proposal") if isinstance(row.get("proposal"), dict) else {}, ensure_ascii=True, sort_keys=True),
            require_text(row, "source", default="crm") or "crm",
            require_text(row, "created_at") or utc_now(),
            require_text(row, "updated_at") or utc_now(),
            require_text(row, "approved_at"),
            require_text(row, "applied_at"),
        ),
    )
    return (_workflow_proposal(db, proposal_id), not exists)


def _workflow_proposal_action_issues(db, proposal: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    proposal_payload = proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {}
    action = proposal_payload.get("action") if isinstance(proposal_payload.get("action"), dict) else {}
    action_type = str(action.get("type") or "")
    if not action_type:
        return ["missing action type"]
    if action_type == "create_task":
        if not str(action.get("title") or "").strip():
            issues.append("create_task missing title")
        for field, entity_type in {"account_id": "account", "contact_id": "contact", "deal_id": "deal"}.items():
            entity_id = str(action.get(field) or "").strip()
            if entity_id and record_exists(db, entity_type, entity_id) != "active":
                issues.append(f"create_task {field} is not active")
    elif action_type == "update_record":
        entity_type = str(action.get("entity_type") or proposal.get("entity_type") or "").strip()
        entity_id = str(action.get("id") or proposal.get("entity_id") or "").strip()
        try:
            table_for_entity(entity_type)
        except ValidationError:
            issues.append("update_record entity_type is invalid")
        else:
            if record_exists(db, entity_type, entity_id) != "active":
                issues.append("update_record target is not active")
        changes = action.get("changes") if isinstance(action.get("changes"), dict) else {}
        custom_fields = changes.get("custom_fields") if isinstance(changes.get("custom_fields"), dict) else None
        standard_changes = {key: value for key, value in changes.items() if key != "custom_fields"}
        if not standard_changes and custom_fields is None:
            issues.append("update_record has no applicable changes")
        if isinstance(custom_fields, dict) and entity_type in ENTITY_TABLES:
            fields = {field["field_key"] for field in list_custom_fields(db, entity_type)}
            unknown = sorted(str(key) for key in custom_fields if str(key) not in fields)
            if unknown:
                issues.append("update_record custom_fields contains unknown keys")
    else:
        issues.append(f"unsupported action type: {action_type}")
    return issues
