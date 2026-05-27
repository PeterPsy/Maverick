"""CRM record enrichment, next-action suggestions, and workflow proposals."""

from __future__ import annotations

from typing import Any

from domains.automation_rules import run_automation_rules
from domains.custom_fields import _standard_fields_for_entity, list_custom_fields
from domains.operations import list_next_actions
from domains.record_lifecycle import title_for_record
from domains.workflow import _create_workflow_proposal
from store import get_record, parse_limit, require_text, row_to_dict


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
    actions.extend(recommendation_next_actions(db))
    actions.sort(key=lambda item: (int(item.get("score") or 0), str(item.get("title") or "")), reverse=True)
    return actions[:limit]


def recommendation_next_actions(db) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    actions.extend(_deal_next_action_suggestions(db))
    actions.extend(_lead_next_action_suggestions(db))
    actions.extend(_account_next_action_suggestions(db))
    actions.sort(key=lambda item: (int(item.get("score") or 0), str(item.get("title") or "")), reverse=True)
    return actions


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
