"""Records table service domain for CRM."""

from __future__ import annotations

import json
from typing import Any

from errors import ValidationError
from store import require_text

from .records_table_query import records_table_query
from .records_table_response import (
    encode_records_table_cursor,
    records_table_columns,
    records_table_counts,
    records_table_records_by_key,
    records_table_row_envelope,
)
from .records_table_sorting import (
    RECORDS_TABLE_SORT_FIELDS,
    records_table_sort_direction,
    records_table_sort_field,
)


RECORDS_TABLE_ENTITY_TYPES = {"all", "lead", "account", "contact", "deal"}


def records_table(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", default="all") or "all"
    if entity_type not in RECORDS_TABLE_ENTITY_TYPES:
        raise ValidationError("Unsupported records table entity_type.", details={"entity_type": entity_type})
    query = require_text(payload, "query")
    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValidationError("`filters` must be an object.")
    sort = payload.get("sort") or {}
    if not isinstance(sort, dict):
        raise ValidationError("`sort` must be an object.")
    pagination = payload.get("pagination") or {}
    if not isinstance(pagination, dict):
        raise ValidationError("`pagination` must be an object.")
    limit = _records_table_limit(pagination)
    cursor = _records_table_cursor(pagination)
    sort_field = records_table_sort_field(sort)
    sort_direction = records_table_sort_direction(sort)
    if cursor and (cursor["sort_field"] != sort_field or cursor["direction"] != sort_direction):
        raise ValidationError("`pagination.cursor` does not match the requested sort.")
    entities = ["lead", "account", "contact", "deal"] if entity_type == "all" else [entity_type]
    sql, params = records_table_query(entities, query, filters, sort_field, sort_direction, cursor, limit + 1)
    rows = db.execute(sql, params).fetchall()
    page_rows = rows[:limit]
    records_by_key = records_table_records_by_key(db, page_rows)
    records = [records_table_row_envelope(row, records_by_key) for row in page_rows]
    has_more = len(rows) > limit
    return {
        "ok": True,
        "records": records,
        "columns": records_table_columns(db, entity_type),
        "counts": records_table_counts(db),
        "next_cursor": encode_records_table_cursor(page_rows[-1], sort_field, sort_direction) if has_more and page_rows else "",
        "has_more": has_more,
    }


def _records_table_limit(pagination: dict[str, Any]) -> int:
    value = pagination.get("limit", 50)
    if not isinstance(value, int):
        raise ValidationError("`pagination.limit` must be an integer.")
    return max(1, min(value, 100))


def _records_table_cursor(pagination: dict[str, Any]) -> dict[str, Any] | None:
    cursor = pagination.get("cursor", "")
    if cursor in (None, ""):
        return None
    if not isinstance(cursor, str):
        raise ValidationError("`pagination.cursor` must be a records table cursor.")
    try:
        decoded = json.loads(cursor)
    except json.JSONDecodeError as error:
        raise ValidationError("`pagination.cursor` must be a records table cursor.") from error
    if not isinstance(decoded, dict):
        raise ValidationError("`pagination.cursor` must be a records table cursor.")
    sort_field = str(decoded.get("sort_field") or "")
    direction = str(decoded.get("direction") or "")
    entity_type = str(decoded.get("entity_type") or "")
    entity_id = str(decoded.get("id") or "")
    if (
        sort_field not in RECORDS_TABLE_SORT_FIELDS
        or direction not in {"asc", "desc"}
        or entity_type not in RECORDS_TABLE_ENTITY_TYPES
        or entity_type == "all"
        or not entity_id
    ):
        raise ValidationError("`pagination.cursor` must be a records table cursor.")
    return {
        "sort_field": sort_field,
        "direction": direction,
        "entity_type": entity_type,
        "id": entity_id,
        "order_text": str(decoded.get("order_text") or ""),
        "order_number": _cursor_number(decoded.get("order_number")),
    }


def _cursor_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError) as error:
        raise ValidationError("`pagination.cursor` must be a records table cursor.") from error
