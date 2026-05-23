"""Records table service domain for CRM."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from errors import ValidationError
from store import count_tables, get_record, require_text


RECORDS_TABLE_ENTITY_TYPES = {"all", "lead", "account", "contact", "deal"}
ENTITY_ROUTE_SEGMENTS = {
    "lead": "leads",
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
}
TABLE_ENTITY_TYPES = {
    "leads": "lead",
    "accounts": "account",
    "contacts": "contact",
    "deals": "deal",
}


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
    sort_field = _records_table_sort_field(sort)
    sort_direction = _records_table_sort_direction(sort)
    if cursor and (cursor["sort_field"] != sort_field or cursor["direction"] != sort_direction):
        raise ValidationError("`pagination.cursor` does not match the requested sort.")
    entities = ["lead", "account", "contact", "deal"] if entity_type == "all" else [entity_type]
    sql, params = _records_table_query(entities, query, filters, sort_field, sort_direction, cursor, limit + 1)
    rows = db.execute(sql, params).fetchall()
    page_rows = rows[:limit]
    records = [_records_table_row_envelope(db, row) for row in page_rows]
    has_more = len(rows) > limit
    return {
        "ok": True,
        "records": records,
        "columns": _records_table_columns(entity_type),
        "counts": _records_table_counts(db),
        "next_cursor": _records_table_encode_cursor(page_rows[-1], sort_field, sort_direction) if has_more and page_rows else "",
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


RECORDS_TABLE_SORT_FIELDS = {
    "updated_at",
    "value",
    "close_date",
    "owner",
    "owner_id",
    "status",
    "stage",
    "name",
    "last_activity_at",
    "next_action",
    "open_task_count",
    "open_deal_value",
    "contact_count",
    "weighted_value",
    "deal_age_days",
    "probability",
}
RECORDS_TABLE_NUMERIC_SORT_FIELDS = {
    "value",
    "open_task_count",
    "open_deal_value",
    "contact_count",
    "weighted_value",
    "deal_age_days",
    "probability",
}


def _records_table_sort_field(sort: dict[str, Any]) -> str:
    field = str(sort.get("field") or "updated_at")
    return field if field in RECORDS_TABLE_SORT_FIELDS else "updated_at"


def _records_table_sort_direction(sort: dict[str, Any]) -> str:
    return "asc" if str(sort.get("direction") or "desc").lower() == "asc" else "desc"


def _records_table_query(
    entities: list[str],
    query: str,
    filters: dict[str, Any],
    sort_field: str,
    sort_direction: str,
    cursor: dict[str, Any] | None,
    limit: int,
) -> tuple[str, list[Any]]:
    selects: list[str] = []
    params: list[Any] = []
    for entity in entities:
        select_sql, select_params = _records_table_entity_select(entity, query, filters, sort_field)
        selects.append(select_sql)
        params.extend(select_params)
    outer_where, outer_params = _records_table_outer_where(filters, sort_field, sort_direction, cursor)
    params.extend(outer_params)
    order_column = "order_number" if sort_field in RECORDS_TABLE_NUMERIC_SORT_FIELDS else "order_text"
    sql = f"""
    WITH
    activity_rollups AS (
      SELECT 'account' AS entity_type, account_id AS entity_id, max(COALESCE(NULLIF(occurred_at, ''), updated_at)) AS last_activity_at
      FROM activities WHERE account_id <> '' AND deleted_at IS NULL AND archived_at IS NULL GROUP BY account_id
      UNION ALL
      SELECT 'contact' AS entity_type, contact_id AS entity_id, max(COALESCE(NULLIF(occurred_at, ''), updated_at)) AS last_activity_at
      FROM activities WHERE contact_id <> '' AND deleted_at IS NULL AND archived_at IS NULL GROUP BY contact_id
      UNION ALL
      SELECT 'deal' AS entity_type, deal_id AS entity_id, max(COALESCE(NULLIF(occurred_at, ''), updated_at)) AS last_activity_at
      FROM activities WHERE deal_id <> '' AND deleted_at IS NULL AND archived_at IS NULL GROUP BY deal_id
    ),
    open_tasks AS (
      SELECT 'account' AS entity_type, account_id AS entity_id, title, due_at, updated_at
      FROM tasks WHERE account_id <> '' AND status = 'open' AND deleted_at IS NULL AND archived_at IS NULL
      UNION ALL
      SELECT 'contact' AS entity_type, contact_id AS entity_id, title, due_at, updated_at
      FROM tasks WHERE contact_id <> '' AND status = 'open' AND deleted_at IS NULL AND archived_at IS NULL
      UNION ALL
      SELECT 'deal' AS entity_type, deal_id AS entity_id, title, due_at, updated_at
      FROM tasks WHERE deal_id <> '' AND status = 'open' AND deleted_at IS NULL AND archived_at IS NULL
    ),
    task_counts AS (
      SELECT entity_type, entity_id, count(*) AS open_task_count
      FROM open_tasks GROUP BY entity_type, entity_id
    ),
    next_tasks AS (
      SELECT entity_type, entity_id, title AS next_action
      FROM (
        SELECT entity_type, entity_id, title,
          row_number() OVER (
            PARTITION BY entity_type, entity_id
            ORDER BY CASE WHEN due_at = '' THEN 1 ELSE 0 END, due_at ASC, updated_at DESC
          ) AS rank
        FROM open_tasks
      )
      WHERE rank = 1
    ),
    deal_rollups AS (
      SELECT 'account' AS entity_type, account_id AS entity_id, COALESCE(sum(value), 0) AS open_deal_value
      FROM deals WHERE account_id <> '' AND lower(stage) NOT IN ('won', 'lost') AND deleted_at IS NULL AND archived_at IS NULL GROUP BY account_id
      UNION ALL
      SELECT 'contact' AS entity_type, contact_id AS entity_id, COALESCE(sum(value), 0) AS open_deal_value
      FROM deals WHERE contact_id <> '' AND lower(stage) NOT IN ('won', 'lost') AND deleted_at IS NULL AND archived_at IS NULL GROUP BY contact_id
    ),
    contact_counts AS (
      SELECT account_id AS entity_id, count(*) AS contact_count
      FROM contacts WHERE account_id <> '' AND deleted_at IS NULL AND archived_at IS NULL GROUP BY account_id
    ),
    records AS (
      {" UNION ALL ".join(selects)}
    )
    SELECT * FROM records
    {outer_where}
    ORDER BY {order_column} {sort_direction.upper()}, entity_type ASC, id ASC
    LIMIT ?
    """
    params.append(limit)
    return sql, params


def _records_table_entity_select(entity_type: str, query: str, filters: dict[str, Any], sort_field: str) -> tuple[str, list[Any]]:
    config = _records_table_entity_config(entity_type)
    where = [f"{config['alias']}.deleted_at IS NULL", f"{config['alias']}.archived_at IS NULL"]
    params: list[Any] = []
    if query:
        where.append(f"lower({config['search']}) LIKE ?")
        params.append(f"%{query.lower()}%")
    filter_sql, filter_params = _records_table_entity_filters(entity_type, config, filters)
    where.extend(filter_sql)
    params.extend(filter_params)
    order_text, order_number = _records_table_order_expressions(entity_type, config, sort_field)
    sql = f"""
      SELECT
        '{entity_type}' AS entity_type,
        {config['alias']}.id AS id,
        {config['title']} AS title,
        {config['alias']}.updated_at AS updated_at,
        {config['alias']}.created_at AS created_at,
        {config['owner']} AS owner_id,
        {config['status']} AS status_value,
        {config['stage']} AS stage_value,
        {config['value']} AS value_value,
        {config['probability']} AS probability_value,
        {config['close_date']} AS close_date,
        {config['last_activity_at']} AS last_activity_at,
        {config['next_action']} AS next_action,
        {config['open_task_count']} AS open_task_count,
        {config['open_deal_value']} AS open_deal_value,
        {config['contact_count']} AS contact_count,
        {config['weighted_value']} AS weighted_value,
        {config['deal_age_days']} AS deal_age_days,
        {order_text} AS order_text,
        {order_number} AS order_number
      FROM {config['table']} {config['alias']}
      {config['joins']}
      WHERE {" AND ".join(where)}
    """
    return sql, params


def _records_table_entity_config(entity_type: str) -> dict[str, str]:
    if entity_type == "lead":
        return {
            "table": "leads",
            "alias": "l",
            "joins": "",
            "title": "l.display_name",
            "search": "l.display_name || ' ' || l.email || ' ' || l.company || ' ' || l.domain || ' ' || l.summary",
            "owner": "l.owner_id",
            "status": "l.status",
            "stage": "''",
            "value": "0",
            "probability": "0",
            "close_date": "''",
            "last_activity_at": "''",
            "next_action": "''",
            "open_task_count": "0",
            "open_deal_value": "0",
            "contact_count": "0",
            "weighted_value": "0",
            "deal_age_days": "0",
        }
    if entity_type == "account":
        return {
            "table": "accounts",
            "alias": "a",
            "joins": """
              LEFT JOIN activity_rollups ar ON ar.entity_type = 'account' AND ar.entity_id = a.id
              LEFT JOIN task_counts tc ON tc.entity_type = 'account' AND tc.entity_id = a.id
              LEFT JOIN next_tasks nt ON nt.entity_type = 'account' AND nt.entity_id = a.id
              LEFT JOIN deal_rollups dr ON dr.entity_type = 'account' AND dr.entity_id = a.id
              LEFT JOIN contact_counts cc ON cc.entity_id = a.id
            """,
            "title": "a.name",
            "search": "a.name || ' ' || a.domain || ' ' || a.industry || ' ' || a.summary",
            "owner": "a.owner_id",
            "status": "a.status",
            "stage": "''",
            "value": "0",
            "probability": "0",
            "close_date": "''",
            "last_activity_at": "COALESCE(ar.last_activity_at, '')",
            "next_action": "COALESCE(nt.next_action, '')",
            "open_task_count": "COALESCE(tc.open_task_count, 0)",
            "open_deal_value": "COALESCE(dr.open_deal_value, 0)",
            "contact_count": "COALESCE(cc.contact_count, 0)",
            "weighted_value": "0",
            "deal_age_days": "0",
        }
    if entity_type == "contact":
        return {
            "table": "contacts",
            "alias": "c",
            "joins": """
              LEFT JOIN activity_rollups ar ON ar.entity_type = 'contact' AND ar.entity_id = c.id
              LEFT JOIN task_counts tc ON tc.entity_type = 'contact' AND tc.entity_id = c.id
              LEFT JOIN next_tasks nt ON nt.entity_type = 'contact' AND nt.entity_id = c.id
              LEFT JOIN deal_rollups dr ON dr.entity_type = 'contact' AND dr.entity_id = c.id
            """,
            "title": "c.display_name",
            "search": "c.display_name || ' ' || c.email || ' ' || c.role || ' ' || c.summary",
            "owner": "c.owner_id",
            "status": "''",
            "stage": "''",
            "value": "0",
            "probability": "0",
            "close_date": "''",
            "last_activity_at": "COALESCE(ar.last_activity_at, '')",
            "next_action": "COALESCE(nt.next_action, '')",
            "open_task_count": "COALESCE(tc.open_task_count, 0)",
            "open_deal_value": "COALESCE(dr.open_deal_value, 0)",
            "contact_count": "0",
            "weighted_value": "0",
            "deal_age_days": "0",
        }
    return {
        "table": "deals",
        "alias": "d",
        "joins": """
          LEFT JOIN activity_rollups ar ON ar.entity_type = 'deal' AND ar.entity_id = d.id
          LEFT JOIN task_counts tc ON tc.entity_type = 'deal' AND tc.entity_id = d.id
          LEFT JOIN next_tasks nt ON nt.entity_type = 'deal' AND nt.entity_id = d.id
        """,
        "title": "d.name",
        "search": "d.name || ' ' || d.stage || ' ' || d.summary",
        "owner": "d.owner_id",
        "status": "d.stage",
        "stage": "COALESCE(NULLIF(d.stage, ''), d.stage_id)",
        "value": "d.value",
        "probability": "d.probability",
        "close_date": "d.close_date",
        "last_activity_at": "COALESCE(ar.last_activity_at, '')",
        "next_action": "COALESCE(nt.next_action, '')",
        "open_task_count": "COALESCE(tc.open_task_count, 0)",
        "open_deal_value": "0",
        "contact_count": "0",
        "weighted_value": "round(d.value * d.probability, 2)",
        "deal_age_days": "CAST(max(0, julianday('now') - julianday(d.created_at)) AS INTEGER)",
    }


def _records_table_entity_filters(entity_type: str, config: dict[str, str], filters: dict[str, Any]) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    alias = config["alias"]
    for key, value in filters.items():
        if value in ("", None, [], {}):
            continue
        if key == "status":
            where.append(f"{config['status']} = ?")
            params.append(str(value))
        elif key == "stage":
            if entity_type == "deal":
                where.append("(d.stage_id = ? OR d.stage = ?)")
                params.extend([str(value), str(value)])
            else:
                where.append("0 = 1")
        elif key == "owner_id":
            where.append(f"{config['owner']} = ?")
            params.append(str(value))
        elif key == "source":
            if entity_type == "lead":
                where.append("l.source = ?")
                params.append(str(value))
            else:
                where.append("0 = 1")
        elif key == "tag":
            where.append(
                """
                EXISTS (
                  SELECT 1 FROM record_tags
                  JOIN tags ON tags.id = record_tags.tag_id
                  WHERE record_tags.record_type = ?
                    AND record_tags.record_id = {alias}.id
                    AND lower(tags.name) = ?
                )
                """.format(alias=alias)
            )
            params.extend([entity_type, str(value).lower()])
        elif key == "min_value":
            where.append(f"CAST({config['value']} AS REAL) >= ?")
            params.append(_filter_number(value, key))
        elif key == "max_value":
            where.append(f"CAST({config['value']} AS REAL) <= ?")
            params.append(_filter_number(value, key))
        elif key == "close_date_from":
            where.append(f"{config['close_date']} >= ?")
            params.append(str(value))
        elif key == "close_date_to":
            where.append(f"{config['close_date']} <= ?")
            params.append(str(value))
        elif key == "custom_fields":
            custom_sql, custom_params = _records_table_custom_field_filters(entity_type, alias, value)
            where.extend(custom_sql)
            params.extend(custom_params)
    return where, params


def _records_table_custom_field_filters(entity_type: str, alias: str, expected: Any) -> tuple[list[str], list[Any]]:
    if not isinstance(expected, dict):
        raise ValidationError("`filters.custom_fields` must be an object.")
    where: list[str] = []
    params: list[Any] = []
    for key, value in expected.items():
        if value in ("", None, [], {}):
            continue
        where.append(
            """
            EXISTS (
              SELECT 1
              FROM custom_field_definitions cfd
              JOIN custom_field_values cfv
                ON cfv.field_id = cfd.id
               AND cfv.entity_type = cfd.entity_type
               AND cfv.entity_id = {alias}.id
              WHERE cfd.entity_type = ?
                AND cfd.field_key = ?
                AND cfd.archived_at IS NULL
                AND cfv.value_json = ?
            )
            """.format(alias=alias)
        )
        params.extend([entity_type, str(key), json.dumps(value, ensure_ascii=True, sort_keys=True)])
    return where, params


def _records_table_outer_where(filters: dict[str, Any], sort_field: str, sort_direction: str, cursor: dict[str, Any] | None) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    for key, value in filters.items():
        if value in ("", None, [], {}):
            continue
        if key in {"last_activity_at", "next_action"}:
            where.append(f"{key} = ?")
            params.append(str(value))
        elif key in {"open_task_count", "open_deal_value", "contact_count", "weighted_value", "deal_age_days"}:
            where.append(f"CAST({key} AS REAL) = ?")
            params.append(_filter_number(value, key))
    if cursor:
        order_column = "order_number" if sort_field in RECORDS_TABLE_NUMERIC_SORT_FIELDS else "order_text"
        order_value = cursor["order_number"] if order_column == "order_number" else cursor["order_text"]
        comparator = ">" if sort_direction == "asc" else "<"
        where.append(
            f"""(
              {order_column} {comparator} ?
              OR ({order_column} = ? AND (entity_type > ? OR (entity_type = ? AND id > ?)))
            )"""
        )
        params.extend([order_value, order_value, cursor["entity_type"], cursor["entity_type"], cursor["id"]])
    return (f"WHERE {' AND '.join(where)}" if where else "", params)


def _records_table_order_expressions(entity_type: str, config: dict[str, str], sort_field: str) -> tuple[str, str]:
    if sort_field in RECORDS_TABLE_NUMERIC_SORT_FIELDS:
        numeric = {
            "value": config["value"],
            "probability": config["probability"],
            "open_task_count": config["open_task_count"],
            "open_deal_value": config["open_deal_value"],
            "contact_count": config["contact_count"],
            "weighted_value": config["weighted_value"],
            "deal_age_days": config["deal_age_days"],
        }[sort_field]
        return "''", f"CAST({numeric} AS REAL)"
    text = {
        "updated_at": f"{config['alias']}.updated_at",
        "close_date": config["close_date"],
        "owner": f"lower({config['owner']})",
        "owner_id": f"lower({config['owner']})",
        "status": f"lower({config['status']})",
        "stage": f"lower({config['stage']})",
        "name": f"lower({config['title']})",
        "last_activity_at": config["last_activity_at"],
        "next_action": f"lower({config['next_action']})",
    }.get(sort_field, f"{config['alias']}.updated_at")
    return f"COALESCE({text}, '')", "0"


def _records_table_row_envelope(db, row: sqlite3.Row) -> dict[str, Any]:
    entity_type = str(row["entity_type"])
    record = get_record(db, entity_type, str(row["id"]))
    computed = {
        "last_activity_at": str(row["last_activity_at"] or ""),
        "next_action": str(row["next_action"] or ""),
        "open_task_count": int(row["open_task_count"] or 0),
    }
    if entity_type == "account":
        computed["open_deal_value"] = float(row["open_deal_value"] or 0)
        computed["contact_count"] = int(row["contact_count"] or 0)
    if entity_type == "contact":
        computed["open_deal_value"] = float(row["open_deal_value"] or 0)
    if entity_type == "deal":
        computed["weighted_value"] = float(row["weighted_value"] or 0)
        computed["deal_age_days"] = int(row["deal_age_days"] or 0)
    return _records_table_envelope(entity_type, record, computed)


def _records_table_envelope(entity_type: str, record: dict[str, Any], computed: dict[str, Any]) -> dict[str, Any]:
    title = title_for_record(record)
    return {
        "entity_type": entity_type,
        "id": record["id"],
        "title": title,
        "record": record,
        "computed": computed,
        "ref": {
            "entity_type": entity_type,
            "entity_id": record["id"],
            "app_page": f"{ENTITY_ROUTE_SEGMENTS[entity_type]}/{record['id']}",
        },
    }


def title_for_record(record: dict[str, Any]) -> str:
    return str(record.get("name") or record.get("display_name") or record.get("subject") or record.get("title") or str(record.get("body") or "")[:48] or record.get("id") or "")


def _filter_number(value: Any, key: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"`filters.{key}` must be a number.") from error


def _records_table_encode_cursor(row: sqlite3.Row, sort_field: str, sort_direction: str) -> str:
    return json.dumps(
        {
            "sort_field": sort_field,
            "direction": sort_direction,
            "entity_type": row["entity_type"],
            "id": row["id"],
            "order_text": row["order_text"],
            "order_number": row["order_number"],
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _records_table_columns(entity_type: str) -> list[dict[str, str]]:
    columns_by_entity = {
        "lead": ["name", "company", "email", "source", "status", "owner", "next_action", "updated"],
        "account": ["name", "domain", "industry", "status", "owner", "open_deal_value", "contact_count", "last_activity", "tags"],
        "contact": ["name", "account", "email", "role", "owner", "last_activity", "open_task_count", "tags"],
        "deal": ["name", "account", "contact", "stage", "value", "probability", "weighted_value", "close_date", "deal_age_days", "owner"],
        "all": ["type", "name", "account_company", "owner", "status_stage", "value", "next_action", "last_touch", "updated", "tags"],
    }
    return [{"key": key, "label": field_label(key)} for key in columns_by_entity[entity_type]]


def _records_table_counts(db) -> dict[str, int]:
    counts = count_tables(db, ["leads", "accounts", "contacts", "deals"])
    return {TABLE_ENTITY_TYPES[table]: count for table, count in counts.items()}


def field_label(key: str) -> str:
    return key.replace("_", " ").title()
