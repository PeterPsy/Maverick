"""CRM record search and filter actions."""

from __future__ import annotations

from typing import Any

from errors import ValidationError
from store import list_rows, parse_limit, require_text, table_for_entity


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
VIEW_ENTITY_TYPES = {"all", *ENTITY_TABLES.keys()}


def view_entity_type(payload: dict[str, Any]) -> str:
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    if entity_type not in VIEW_ENTITY_TYPES:
        raise ValidationError("Unsupported CRM view entity_type.", details={"entity_type": entity_type})
    return entity_type


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
            if _record_matches_filters(entity, record, filters):
                record["entity_type"] = entity
                records.append(record)
    return {"ok": True, "entity_type": entity_type, "records": records[:limit]}


def _record_matches_filters(entity_type: str, record: dict[str, Any], filters: dict[str, Any]) -> bool:
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
