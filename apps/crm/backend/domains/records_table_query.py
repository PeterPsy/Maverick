"""SQL query construction for the CRM records table."""

from __future__ import annotations

import json
from typing import Any

from errors import ValidationError

from .records_table_entities import records_table_entity_config
from .records_table_sorting import RECORDS_TABLE_NUMERIC_SORT_FIELDS


def records_table_query(
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
    config = records_table_entity_config(entity_type)
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
        {config['account_label']} AS account_label,
        {config['contact_label']} AS contact_label,
        {order_text} AS order_text,
        {order_number} AS order_number
      FROM {config['table']} {config['alias']}
      {config['joins']}
      WHERE {" AND ".join(where)}
    """
    return sql, params


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


def _filter_number(value: Any, key: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"`filters.{key}` must be a number.") from error
