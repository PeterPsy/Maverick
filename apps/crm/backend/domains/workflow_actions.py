"""CRM workflow proposal validation and application."""

from __future__ import annotations

from typing import Any

from errors import NotFoundError, ValidationError
from domains.custom_fields import list_custom_fields, set_custom_fields
from domains.record_lifecycle import record_exists
from domains.record_mutations import _update_entity_record, create_task
from domains.workflow import _workflow_proposal, approve_workflow_proposal
from store import get_record, require_text, table_for_entity, utc_now, write_event


ENTITY_TABLES = {
    "lead": "leads",
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "task": "tasks",
    "note": "notes",
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
        changes = dict(action.get("changes") if isinstance(action.get("changes"), dict) else {})
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


def workflow_proposal_preview(db, payload: dict[str, Any]) -> dict[str, Any]:
    proposal_id = require_text(payload, "id", required=True)
    proposal = _workflow_proposal(db, proposal_id)
    proposal_payload = proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {}
    action = proposal_payload.get("action") if isinstance(proposal_payload.get("action"), dict) else {}
    action_type = str(action.get("type") or "")
    issues = workflow_proposal_action_issues(db, proposal)
    preview = {
        "proposal_id": proposal_id,
        "status": proposal.get("status") or "",
        "action_type": action_type,
        "target": _workflow_action_target(proposal, action),
        "changes": _workflow_action_changes(db, proposal, action),
        "proposed_task": _workflow_action_task(action) if action_type == "create_task" else None,
        "validation_issues": issues,
        "can_approve": proposal.get("status") in {"pending", "approved"} and not issues,
        "can_apply": proposal.get("status") == "approved" and not issues,
    }
    return {"ok": True, "workflow_proposal": proposal, "preview": preview}


def workflow_proposal_action_issues(db, proposal: dict[str, Any]) -> list[str]:
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


def _workflow_action_target(proposal: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    entity_type = str(action.get("entity_type") or proposal.get("entity_type") or "").strip()
    entity_id = str(action.get("id") or proposal.get("entity_id") or "").strip()
    return {"entity_type": entity_type, "id": entity_id}


def _workflow_action_changes(db, proposal: dict[str, Any], action: dict[str, Any]) -> list[dict[str, Any]]:
    if str(action.get("type") or "") != "update_record":
        return []
    target = _workflow_action_target(proposal, action)
    current_record = _workflow_preview_record(db, target["entity_type"], target["id"])
    changes = action.get("changes") if isinstance(action.get("changes"), dict) else {}
    preview_changes: list[dict[str, Any]] = []
    for field, proposed_value in changes.items():
        if field == "custom_fields":
            continue
        current_value = current_record.get(field) if current_record else None
        if current_record is None or current_value != proposed_value:
            preview_changes.append({"field": str(field), "current_value": current_value, "proposed_value": proposed_value})
    custom_fields = changes.get("custom_fields") if isinstance(changes.get("custom_fields"), dict) else {}
    current_custom_fields = current_record.get("custom_fields") if isinstance(current_record, dict) and isinstance(current_record.get("custom_fields"), dict) else {}
    for field, proposed_value in custom_fields.items():
        field_key = str(field)
        current_value = current_custom_fields.get(field_key)
        if current_record is None or current_value != proposed_value:
            preview_changes.append({"field": f"custom_fields.{field_key}", "current_value": current_value, "proposed_value": proposed_value})
    return preview_changes


def _workflow_action_task(action: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in action.items() if key != "type"}


def _workflow_preview_record(db, entity_type: str, entity_id: str) -> dict[str, Any] | None:
    if not entity_type or not entity_id:
        return None
    try:
        return get_record(db, entity_type, entity_id)
    except (NotFoundError, ValidationError):
        return None
