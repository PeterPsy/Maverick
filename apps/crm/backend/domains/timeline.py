"""Record timeline assembly for CRM entities."""

from __future__ import annotations

from typing import Any

from store import attach_tags, get_record, require_text, row_to_dict

from .connection_summary import connection_summary_for_ref_context
from .external_refs import external_timeline_rows


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
    for external_ref in external_timeline_rows(db, refs, (entity_type, entity_id)):
        items.append(external_ref)
    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return {"ok": True, "entity_type": entity_type, "id": entity_id, "items": items[:100]}


def external_timeline(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    get_record(db, entity_type, entity_id)
    refs = _timeline_refs(db, entity_type, entity_id)
    items = external_timeline_rows(db, refs, (entity_type, entity_id))
    return {
        "ok": True,
        "entity_type": entity_type,
        "id": entity_id,
        "items": items[:100],
        "connection_summary": connection_summary_for_ref_context(db, refs),
    }


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
