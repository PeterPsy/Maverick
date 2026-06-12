"""UI-ready Operations feed aggregation for CRM."""

from __future__ import annotations

from typing import Any

from domains.record_intelligence import recommendation_next_actions
from store import parse_limit, row_to_dict, utc_now

from .connection_summary import connection_summaries_for_deals, connection_summaries_for_records


def operations_feed(db, payload: dict[str, Any]) -> dict[str, Any]:
    limit = parse_limit(payload, 20)
    filters = _feed_filters(payload)
    to_do_items = _to_do_items(db, filters)
    active_proposal_items = _workflow_proposal_items(db, ("pending", "approved"), filters)
    applied_proposal_items = _workflow_proposal_items(db, ("applied",), filters)
    discarded_proposal_items = _workflow_proposal_items(db, ("dismissed", "rejected"), filters)
    audit_items = _audit_items(db, filters)
    sections = [
        {
            "key": "to_do",
            "title": "Da fare",
            "count": len(to_do_items),
            "items": to_do_items[:limit],
        },
        {
            "key": "to_approve",
            "title": "Da approvare",
            "count": len(active_proposal_items),
            "items": active_proposal_items[:limit],
        },
        {
            "key": "done",
            "title": "Fatto",
            "count": len(applied_proposal_items),
            "items": applied_proposal_items[:limit],
        },
        {
            "key": "discarded",
            "title": "Scartato",
            "count": len(discarded_proposal_items),
            "items": discarded_proposal_items[:limit],
        },
        {
            "key": "audit",
            "title": "Audit recente",
            "count": len(audit_items),
            "items": audit_items[:limit],
        },
    ]
    return {
        "ok": True,
        "generated_at": utc_now(),
        "limit": limit,
        "counts": {section["key"]: section["count"] for section in sections},
        "sections": sections,
    }


def _feed_filters(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "owner_id": str(payload.get("owner_id") or "").strip(),
        "statuses": _value_set(payload.get("status")),
        "kinds": _value_set(payload.get("kind")),
        "due_before": str(payload.get("due_before") or "").strip(),
        "due_overdue": _truthy(payload.get("due_overdue")),
        "now": utc_now(),
    }


def _value_set(value: Any) -> set[str]:
    if value is None or value == "" or value == "all":
        return set()
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip() and part.strip() != "all"}
    if isinstance(value, list):
        return {str(part).strip() for part in value if str(part).strip() and str(part).strip() != "all"}
    return {str(value).strip()} if str(value).strip() else set()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "overdue"}
    return bool(value)


def _to_do_items(db, filters: dict[str, Any]) -> list[dict[str, Any]]:
    task_rows = [row_to_dict(row) for row in _open_task_rows(db)]
    task_items = [_task_feed_item(row) for row in task_rows]
    task_dedupe_keys = set().union(*(_task_dedupe_keys(row) for row in task_rows)) if task_rows else set()
    recommendation_items = [
        item
        for item in _recommendation_items(db)
        if not (_recommendation_dedupe_keys(item) & task_dedupe_keys)
    ]
    items = [item for item in [*task_items, *recommendation_items] if _item_matches(db, item, filters)]
    return sorted(items, key=_to_do_sort_key)


def _open_task_rows(db):
    return db.execute(
        """
        SELECT * FROM tasks
        WHERE deleted_at IS NULL AND archived_at IS NULL AND status = 'open'
        ORDER BY CASE WHEN due_at = '' THEN 1 ELSE 0 END, due_at ASC, updated_at DESC
        """
    ).fetchall()


def _recommendation_items(db) -> list[dict[str, Any]]:
    return [_recommendation_feed_item(action) for action in recommendation_next_actions(db)]


def _workflow_proposal_items(db, statuses: tuple[str, ...], filters: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in (_workflow_proposal_feed_item(db, row_to_dict(row)) for row in _workflow_proposal_rows(db, statuses))
        if _item_matches(db, item, filters)
    ]


def _workflow_proposal_rows(db, statuses: tuple[str, ...]):
    placeholders = ", ".join("?" for _ in statuses)
    return db.execute(
        f"""
        SELECT * FROM workflow_proposals
        WHERE status IN ({placeholders})
        ORDER BY updated_at DESC
        """,
        statuses,
    ).fetchall()


def _audit_items(db, filters: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in (_audit_feed_item(row_to_dict(row)) for row in _recent_operations_event_rows(db))
        if _item_matches(db, item, filters)
    ]


def _recent_operations_event_rows(db):
    return db.execute(
        f"""
        SELECT * FROM events
        WHERE {_operations_event_where()}
        ORDER BY created_at DESC
        """
    ).fetchall()


def _operations_event_where() -> str:
    return """
        event_type LIKE 'task.%'
        OR event_type LIKE 'workflow_proposal.%'
        OR event_type LIKE 'automation_rule.%'
        OR event_type = 'record.merged'
    """


def _task_feed_item(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "task",
        "ref": {"entity_type": "task", "entity_id": task["id"]},
        "status": str(task.get("status") or ""),
        "title": str(task.get("title") or "Task"),
        "reason": "Open CRM task",
        "source": "crm.tasks",
        "priority": task.get("priority") or "",
        "due_at": task.get("due_at") or "",
        "updated_at": task.get("updated_at") or "",
        "owner_id": task.get("owner_id") or "",
    }


def _recommendation_feed_item(action: dict[str, Any]) -> dict[str, Any]:
    proposal_action = action.get("action") if isinstance(action.get("action"), dict) else {}
    return {
        "kind": "recommendation",
        "ref": {
            "entity_type": action.get("entity_type") or "",
            "entity_id": action.get("entity_id") or "",
        },
        "status": "recommended",
        "title": action.get("title") or "Recommended next action",
        "reason": action.get("reason") or "",
        "source": "crm.next_actions",
        "score": int(action.get("score") or 0),
        "action_type": proposal_action.get("type") or "",
        "action": proposal_action,
    }


def _workflow_proposal_feed_item(db, proposal: dict[str, Any]) -> dict[str, Any]:
    proposal_payload = proposal.get("proposal") if isinstance(proposal.get("proposal"), dict) else {}
    action = proposal_payload.get("action") if isinstance(proposal_payload.get("action"), dict) else {}
    evidence = _proposal_evidence(db, proposal, proposal_payload)
    return {
        "kind": "workflow_proposal",
        "ref": {
            "entity_type": proposal.get("entity_type") or "",
            "entity_id": proposal.get("entity_id") or "",
            "proposal_id": proposal.get("id") or "",
        },
        "status": proposal.get("status") or "",
        "title": proposal.get("title") or "Workflow proposal",
        "reason": proposal_payload.get("reason")
        or _workflow_proposal_event_reason(db, proposal)
        or proposal.get("proposal_type")
        or "",
        "source": proposal.get("source") or "crm.workflow",
        "evidence": evidence,
        "action_type": action.get("type") or "",
        "created_at": proposal.get("created_at") or "",
        "updated_at": proposal.get("updated_at") or "",
        "approved_at": proposal.get("approved_at") or "",
        "applied_at": proposal.get("applied_at") or "",
    }


def _proposal_evidence(db, proposal: dict[str, Any], proposal_payload: dict[str, Any]) -> list[str]:
    explicit = proposal_payload.get("evidence") or proposal_payload.get("proof") or proposal_payload.get("source_evidence")
    labels = _evidence_labels(explicit)
    entity_type = str(proposal.get("entity_type") or "")
    entity_id = str(proposal.get("entity_id") or "")
    summary = _proposal_connection_summary(db, entity_type, entity_id)
    mail_count = int(summary.get("mail_count") or 0)
    if mail_count:
        labels.append(f"from {mail_count} {'email' if mail_count == 1 else 'emails'}")
    if int(summary.get("calendar_count") or 0):
        labels.append("calendar event created")
    if summary.get("brief_ready") or int(summary.get("file_count") or 0):
        labels.append("brief saved" if summary.get("brief_ready") else "file linked")
    if proposal.get("status") == "pending":
        labels.append("requires approval")
    return _dedupe(labels)[:5]


def _proposal_connection_summary(db, entity_type: str, entity_id: str) -> dict[str, Any]:
    if entity_type == "deal" and entity_id:
        row = db.execute("SELECT * FROM deals WHERE id = ? AND deleted_at IS NULL", (entity_id,)).fetchone()
        if row is not None:
            return connection_summaries_for_deals(db, [row_to_dict(row)]).get(entity_id, {})
    return connection_summaries_for_records(db, [(entity_type, entity_id)]).get((entity_type, entity_id), {})


def _evidence_labels(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            labels.append(item.strip())
        elif isinstance(item, dict):
            label = item.get("label") or item.get("title") or item.get("summary")
            if label:
                labels.append(str(label))
    return labels


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value.strip())
    return result


def _workflow_proposal_event_reason(db, proposal: dict[str, Any]) -> str:
    proposal_id = str(proposal.get("id") or "")
    status = str(proposal.get("status") or "")
    if not proposal_id or status not in {"dismissed", "rejected"}:
        return ""
    row = db.execute(
        """
        SELECT * FROM events
        WHERE event_type = ?
          AND payload_json LIKE ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (f"workflow_proposal.{status}", f"%{proposal_id}%"),
    ).fetchone()
    if row is None:
        return ""
    event = row_to_dict(row)
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return str(payload.get("reason") or "")


def _audit_feed_item(event: dict[str, Any]) -> dict[str, Any]:
    event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return {
        "kind": "audit_event",
        "ref": {
            "event_id": event.get("id") or "",
            "entity_type": event.get("entity_type") or "",
            "entity_id": event.get("entity_id") or "",
        },
        "status": event_payload.get("status") or "",
        "title": event.get("event_type") or "audit event",
        "reason": event_payload.get("reason")
        or event_payload.get("action_type")
        or event_payload.get("proposal_type")
        or "",
        "source": "crm.audit",
        "created_at": event.get("created_at") or "",
    }


def _item_matches(db, item: dict[str, Any], filters: dict[str, Any]) -> bool:
    kinds = filters["kinds"]
    if kinds and str(item.get("kind") or "") not in kinds:
        return False
    statuses = filters["statuses"]
    if statuses and str(item.get("status") or "") not in statuses:
        return False
    due_at = str(item.get("due_at") or "")
    if filters["due_overdue"] and (not due_at or due_at >= filters["now"]):
        return False
    due_before = str(filters["due_before"] or "")
    if due_before and (not due_at or due_at > due_before):
        return False
    owner_id = str(filters["owner_id"] or "")
    if owner_id and _item_owner(db, item) != owner_id:
        return False
    return True


def _item_owner(db, item: dict[str, Any]) -> str:
    owner_id = str(item.get("owner_id") or "")
    if owner_id:
        return owner_id
    ref = item.get("ref") if isinstance(item.get("ref"), dict) else {}
    return _record_owner(db, str(ref.get("entity_type") or ""), str(ref.get("entity_id") or ""))


def _record_owner(db, entity_type: str, entity_id: str) -> str:
    table = {
        "lead": "leads",
        "account": "accounts",
        "contact": "contacts",
        "deal": "deals",
        "activity": "activities",
        "task": "tasks",
        "note": "notes",
    }.get(entity_type)
    if not table or not entity_id:
        return ""
    row = db.execute(f"SELECT owner_id FROM {table} WHERE id = ? LIMIT 1", (entity_id,)).fetchone()
    return str(row["owner_id"] or "") if row is not None else ""


def _task_dedupe_keys(task: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for key, entity_type in (("account_id", "account"), ("contact_id", "contact"), ("deal_id", "deal")):
        value = str(task.get(key) or "")
        if value:
            keys.add(f"{entity_type}:{value}")
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    lead_id = str(metadata.get("lead_id") or "")
    if lead_id:
        keys.add(f"lead:{lead_id}")
    return keys


def _recommendation_dedupe_keys(item: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    ref = item.get("ref") if isinstance(item.get("ref"), dict) else {}
    entity_type = str(ref.get("entity_type") or "")
    entity_id = str(ref.get("entity_id") or "")
    if entity_type and entity_id:
        keys.add(f"{entity_type}:{entity_id}")
    action = item.get("action") if isinstance(item.get("action"), dict) else {}
    for key, action_entity_type in (("account_id", "account"), ("contact_id", "contact"), ("deal_id", "deal")):
        value = str(action.get(key) or "")
        if value:
            keys.add(f"{action_entity_type}:{value}")
    metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
    lead_id = str(metadata.get("lead_id") or "")
    if lead_id:
        keys.add(f"lead:{lead_id}")
    return keys


def _to_do_sort_key(item: dict[str, Any]) -> tuple[int, str, int, str]:
    due_at = str(item.get("due_at") or "")
    updated_at = str(item.get("updated_at") or "")
    score = int(item.get("score") or 0)
    return (0 if due_at else 1, due_at or updated_at, -score, str(item.get("title") or ""))
