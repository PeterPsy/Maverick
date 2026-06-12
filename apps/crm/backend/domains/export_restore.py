"""Restore full CRM export payloads into app-owned storage."""

from __future__ import annotations

import json
from typing import Any

from errors import ValidationError
from store import new_id, require_text, row_to_dict, utc_now

from .custom_fields import _upsert_custom_field_definition_export, _upsert_custom_field_value_export
from .export_records import TABLE_ENTITY_TYPES, upsert_export_record
from .external_refs import _upsert_external_ref_export
from .workflow import _workflow_proposal


EXPORT_ENTITY_ORDER = ["leads", "accounts", "contacts", "deals", "activities", "tasks", "notes"]
EXPORT_CONFIG_TABLES = ["custom_field_definitions", "custom_field_values", "automation_rules", "workflow_proposals", "external_refs"]


def restore_export_payload(db, payload: dict[str, Any]) -> dict[str, Any]:
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
            record, was_created = upsert_export_record(db, entity_type, row)
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
