"""Shared CRM record lifecycle rules."""

from __future__ import annotations

from typing import Any

from errors import NotFoundError, ValidationError
from store import attach_tags, require_text, row_to_dict, table_for_entity, upsert_fts


ENTITY_ROUTE_SEGMENTS = {
    "lead": "leads",
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "task": "tasks",
    "note": "notes",
}


def get_non_deleted_record(db, entity_type: str, entity_id: str) -> dict[str, Any]:
    table = table_for_entity(entity_type)
    row = db.execute(f"SELECT * FROM {table} WHERE id = ? AND deleted_at IS NULL", (entity_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"{entity_type} `{entity_id}` was not found.")
    record = row_to_dict(row)
    record["entity_type"] = entity_type
    return attach_tags(db, entity_type, record)


def ensure_no_dependents(db, entity_type: str, entity_id: str) -> None:
    dependency_queries = {
        "account": {
            "contacts": "SELECT count(*) FROM contacts WHERE account_id = ? AND deleted_at IS NULL",
            "deals": "SELECT count(*) FROM deals WHERE account_id = ? AND deleted_at IS NULL",
            "activities": "SELECT count(*) FROM activities WHERE account_id = ? AND deleted_at IS NULL",
            "tasks": "SELECT count(*) FROM tasks WHERE account_id = ? AND deleted_at IS NULL",
            "notes": "SELECT count(*) FROM notes WHERE account_id = ? AND deleted_at IS NULL",
        },
        "contact": {
            "deals": "SELECT count(*) FROM deals WHERE contact_id = ? AND deleted_at IS NULL",
            "activities": "SELECT count(*) FROM activities WHERE contact_id = ? AND deleted_at IS NULL",
            "tasks": "SELECT count(*) FROM tasks WHERE contact_id = ? AND deleted_at IS NULL",
            "notes": "SELECT count(*) FROM notes WHERE contact_id = ? AND deleted_at IS NULL",
        },
        "deal": {
            "activities": "SELECT count(*) FROM activities WHERE deal_id = ? AND deleted_at IS NULL",
            "tasks": "SELECT count(*) FROM tasks WHERE deal_id = ? AND deleted_at IS NULL",
            "notes": "SELECT count(*) FROM notes WHERE deal_id = ? AND deleted_at IS NULL",
        },
    }
    counts = {name: int(db.execute(sql, (entity_id,)).fetchone()[0]) for name, sql in dependency_queries.get(entity_type, {}).items()}
    if any(counts.values()):
        raise ValidationError("Cannot delete CRM record while active linked records exist.", details={"entity_type": entity_type, "id": entity_id, "dependents": counts})


def reindex_record(db, entity_type: str, record: dict[str, Any]) -> None:
    upsert_fts(db, entity_type, str(record["id"]), title_for_record(record), fts_body(record))


def fts_body(record: dict[str, Any]) -> str:
    parts = []
    for key in ("domain", "industry", "company", "source", "summary", "email", "role", "stage", "body", "status", "priority", "activity_type"):
        value = record.get(key)
        if value:
            parts.append(str(value))
    custom_fields = record.get("custom_fields") if isinstance(record.get("custom_fields"), dict) else {}
    for value in custom_fields.values():
        if value:
            parts.append(" ".join(str(item) for item in value) if isinstance(value, list) else str(value))
    return " ".join(parts)


def record_exists(db, entity_type: str, entity_id: str) -> str:
    if not entity_id:
        return ""
    table = table_for_entity(entity_type)
    row = db.execute(f"SELECT archived_at, deleted_at FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        return ""
    if row["deleted_at"]:
        return "deleted"
    if row["archived_at"]:
        return "archived"
    return "active"


def validate_relationships(db, payload: dict[str, Any], fields: tuple[str, ...]) -> None:
    mapping = {"account_id": "account", "contact_id": "contact", "deal_id": "deal"}
    for field in fields:
        entity_id = require_text(payload, field)
        if not entity_id:
            continue
        state = record_exists(db, mapping[field], entity_id)
        if state == "archived":
            raise ValidationError("Related CRM record is archived.", details={"field": field, "id": entity_id})
        if state != "active":
            raise ValidationError("Related CRM record was not found.", details={"field": field, "id": entity_id, "state": state or "missing"})


def title_for_record(record: dict[str, Any]) -> str:
    return str(record.get("name") or record.get("display_name") or record.get("subject") or record.get("title") or note_title(record) or record.get("id") or "")


def note_title(record: dict[str, Any]) -> str:
    body = str(record.get("body") or "").strip()
    return body[:48] if body else ""
