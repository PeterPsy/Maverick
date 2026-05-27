"""CRM automation rule storage and execution."""

from __future__ import annotations

import json
from typing import Any

from errors import NotFoundError, ValidationError
from domains.record_lifecycle import title_for_record
from domains.workflow import _create_workflow_proposal, _workflow_proposal_duplicate_exists
from domains.workflow_actions import workflow_proposal_action_issues
from store import attach_tags, get_record, new_id, parse_limit, require_text, row_to_dict, table_for_entity, utc_now, write_event


VIEW_ENTITY_TYPES = {"all", "lead", "account", "contact", "deal", "activity", "task", "note"}
AUTOMATION_ENTITY_TYPES = ("lead", "account", "contact", "deal")


def list_automation_rules(db) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM automation_rules ORDER BY updated_at DESC").fetchall()
    return [row_to_dict(row) for row in rows]


def create_automation_rule(db, payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    rule_id = require_text(payload, "id") or new_id("auto")
    trigger_event = require_text(payload, "trigger_event", required=True)
    entity_type = _automation_entity_type(payload)
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
            _automation_entity_type(merged),
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
                issues = workflow_proposal_action_issues(db, candidate)
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


def _automation_entity_type(payload: dict[str, Any]) -> str:
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    if entity_type not in VIEW_ENTITY_TYPES:
        raise ValidationError("Unsupported CRM view entity_type.", details={"entity_type": entity_type})
    return entity_type


def _automation_rule_entity_types(rule: dict[str, Any]) -> list[str]:
    entity_type = str(rule.get("entity_type") or "all")
    if entity_type == "all":
        return list(AUTOMATION_ENTITY_TYPES)
    return [entity_type] if entity_type in AUTOMATION_ENTITY_TYPES else []


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
