"""Operational CRM queues, duplicates, and audit helpers."""

from __future__ import annotations

from typing import Any

from store import attach_tags, parse_limit, require_text, row_to_dict, table_for_entity


ENTITY_TABLES = {
    "lead": "leads",
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "task": "tasks",
    "note": "notes",
}


def list_next_actions(db, payload: dict[str, Any]) -> list[dict[str, Any]]:
    limit = parse_limit(payload)
    query = require_text(payload, "query")
    params: list[Any] = []
    where = "deleted_at IS NULL AND archived_at IS NULL AND status = 'open'"
    if query:
        where += " AND lower(title || ' ' || body || ' ' || priority) LIKE ?"
        params.append(f"%{query.lower()}%")
    params.append(limit)
    rows = db.execute(
        f"""
        SELECT * FROM tasks
        WHERE {where}
        ORDER BY CASE WHEN due_at = '' THEN 1 ELSE 0 END, due_at ASC, updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [attach_tags(db, "task", row_to_dict(row)) for row in rows]


def find_duplicates(db, payload: dict[str, Any]) -> dict[str, Any]:
    limit = parse_limit(payload, 25)
    groups: list[dict[str, Any]] = []
    groups.extend(_duplicate_groups(db, "account", "accounts", "domain", limit))
    groups.extend(_duplicate_groups(db, "account", "accounts", "name", limit))
    groups.extend(_duplicate_groups(db, "contact", "contacts", "email", limit))
    groups.extend(_duplicate_groups(db, "lead", "leads", "email", limit))
    groups.extend(_duplicate_groups(db, "lead", "leads", "domain", limit))
    return {"ok": True, "groups": groups[:limit]}


def audit_log(db, payload: dict[str, Any]) -> dict[str, Any]:
    where = ["1 = 1"]
    params: list[Any] = []
    entity_type = require_text(payload, "entity_type")
    if entity_type and entity_type != "all":
        table_for_entity(entity_type) if entity_type in ENTITY_TABLES else None
        where.append("entity_type = ?")
        params.append(entity_type)
    entity_id = require_text(payload, "entity_id") or require_text(payload, "id")
    if entity_id:
        where.append("entity_id = ?")
        params.append(entity_id)
    event_type = require_text(payload, "event_type") or require_text(payload, "action")
    if event_type:
        where.append("event_type = ?")
        params.append(event_type)
    date_from = require_text(payload, "date_from") or require_text(payload, "from")
    if date_from:
        where.append("created_at >= ?")
        params.append(date_from)
    date_to = require_text(payload, "date_to") or require_text(payload, "to")
    if date_to:
        where.append("created_at <= ?")
        params.append(date_to)
    params.append(parse_limit(payload, 100))
    rows = db.execute(
        f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return {"ok": True, "events": [row_to_dict(row) for row in rows]}


def _duplicate_groups(db, entity_type: str, table: str, field: str, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        f"""
        SELECT lower(trim({field})) AS duplicate_key, count(*) AS count
        FROM {table}
        WHERE deleted_at IS NULL AND archived_at IS NULL AND trim({field}) != ''
        GROUP BY lower(trim({field}))
        HAVING count(*) > 1
        ORDER BY count(*) DESC, duplicate_key ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    groups = []
    for row in rows:
        records = db.execute(
            f"SELECT * FROM {table} WHERE deleted_at IS NULL AND archived_at IS NULL AND lower(trim({field})) = ? ORDER BY updated_at DESC",
            (row["duplicate_key"],),
        ).fetchall()
        groups.append(
            {
                "entity_type": entity_type,
                "field": field,
                "value": row["duplicate_key"],
                "count": int(row["count"]),
                "records": [attach_tags(db, entity_type, row_to_dict(record)) for record in records],
            }
        )
    return groups
