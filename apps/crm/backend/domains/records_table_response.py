"""Response shaping for the CRM records table."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from store import count_tables, row_to_dict, table_for_entity

from .connection_summary import connection_summaries_for_records
from .record_lifecycle import ENTITY_ROUTE_SEGMENTS, title_for_record


TABLE_ENTITY_TYPES = {
    "leads": "lead",
    "accounts": "account",
    "contacts": "contact",
    "deals": "deal",
}


def records_table_records_by_key(db: sqlite3.Connection, rows: list[sqlite3.Row]) -> dict[tuple[str, str], dict[str, Any]]:
    records = _records_table_base_records(db, rows)
    _attach_records_table_tags(db, records)
    _attach_records_table_custom_fields(db, records)
    _attach_records_table_connection_summaries(db, records)
    return records


def records_table_row_envelope(row: sqlite3.Row, records_by_key: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    entity_type = str(row["entity_type"])
    record = records_by_key[(entity_type, str(row["id"]))]
    computed = {
        "last_activity_at": str(row["last_activity_at"] or ""),
        "next_action": str(row["next_action"] or ""),
        "open_task_count": int(row["open_task_count"] or 0),
        "connection_summary": record.get("connection_summary", {}),
    }
    if entity_type == "account":
        computed["open_deal_value"] = float(row["open_deal_value"] or 0)
        computed["contact_count"] = int(row["contact_count"] or 0)
    if entity_type == "contact":
        computed["open_deal_value"] = float(row["open_deal_value"] or 0)
    if entity_type == "deal":
        computed["weighted_value"] = float(row["weighted_value"] or 0)
        computed["deal_age_days"] = int(row["deal_age_days"] or 0)
    display = {
        "account": str(row["account_label"] or ""),
        "contact": str(row["contact_label"] or ""),
    }
    return _records_table_envelope(entity_type, record, computed, display)


def encode_records_table_cursor(row: sqlite3.Row, sort_field: str, sort_direction: str) -> str:
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


def records_table_columns(db, entity_type: str) -> list[dict[str, str]]:
    columns_by_entity = {
        "lead": ["name", "company", "email", "source", "status", "owner", "connections", "next_action", "updated"],
        "account": ["name", "domain", "industry", "status", "owner", "connections", "open_deal_value", "contact_count", "last_activity", "tags"],
        "contact": ["name", "account", "email", "role", "owner", "connections", "last_activity", "open_task_count", "tags"],
        "deal": ["name", "account", "contact", "stage", "value", "probability", "connections", "weighted_value", "close_date", "deal_age_days", "owner"],
        "all": ["type", "name", "account_company", "owner", "status_stage", "value", "connections", "next_action", "last_touch", "updated", "tags"],
    }
    columns = [{"key": key, "label": _field_label(key)} for key in columns_by_entity[entity_type]]
    columns.extend(_custom_field_columns(db, entity_type))
    return columns


def records_table_counts(db) -> dict[str, int]:
    counts = count_tables(db, ["leads", "accounts", "contacts", "deals"])
    return {TABLE_ENTITY_TYPES[table]: count for table, count in counts.items()}


def _records_table_base_records(db: sqlite3.Connection, rows: list[sqlite3.Row]) -> dict[tuple[str, str], dict[str, Any]]:
    ids_by_entity: dict[str, list[str]] = {}
    for row in rows:
        entity_type = str(row["entity_type"])
        entity_id = str(row["id"])
        ids_by_entity.setdefault(entity_type, []).append(entity_id)

    records: dict[tuple[str, str], dict[str, Any]] = {}
    for entity_type, entity_ids in ids_by_entity.items():
        placeholders = ", ".join("?" for _ in entity_ids)
        table = table_for_entity(entity_type)
        hydrated_rows = db.execute(
            f"""
            SELECT *
            FROM {table}
            WHERE id IN ({placeholders})
              AND deleted_at IS NULL
              AND archived_at IS NULL
            """,
            entity_ids,
        ).fetchall()
        for hydrated_row in hydrated_rows:
            record = row_to_dict(hydrated_row)
            record["entity_type"] = entity_type
            record["tags"] = []
            record["custom_fields"] = {}
            records[(entity_type, str(record["id"]))] = record
    return records


def _attach_records_table_tags(db: sqlite3.Connection, records: dict[tuple[str, str], dict[str, Any]]) -> None:
    where_sql, params = _records_table_entity_id_where("record_tags.record_type", "record_tags.record_id", records)
    if not where_sql:
        return
    for row in db.execute(
        f"""
        SELECT record_tags.record_type, record_tags.record_id, tags.id, tags.name, tags.color, record_tags.created_at
        FROM record_tags
        JOIN tags ON tags.id = record_tags.tag_id
        WHERE {where_sql}
        ORDER BY record_tags.record_type, record_tags.record_id, lower(tags.name)
        """,
        params,
    ).fetchall():
        key = (str(row["record_type"]), str(row["record_id"]))
        record = records.get(key)
        if record is not None:
            record["tags"].append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "color": row["color"],
                    "created_at": row["created_at"],
                }
            )


def _attach_records_table_custom_fields(db: sqlite3.Connection, records: dict[tuple[str, str], dict[str, Any]]) -> None:
    entities = sorted({entity_type for entity_type, _ in records})
    if not entities:
        return
    entity_placeholders = ", ".join("?" for _ in entities)
    definition_rows = db.execute(
        f"""
        SELECT id, entity_type, field_key
        FROM custom_field_definitions
        WHERE archived_at IS NULL
          AND entity_type IN ({entity_placeholders})
        ORDER BY entity_type, position, lower(label)
        """,
        entities,
    ).fetchall()
    definitions_by_entity: dict[str, dict[str, str]] = {}
    for row in definition_rows:
        entity_type = str(row["entity_type"])
        field_key = str(row["field_key"])
        definitions_by_entity.setdefault(entity_type, {})[str(row["id"])] = field_key

    for (entity_type, _), record in records.items():
        record["custom_fields"] = {field_key: None for field_key in definitions_by_entity.get(entity_type, {}).values()}

    where_sql, params = _records_table_entity_id_where("custom_field_values.entity_type", "custom_field_values.entity_id", records)
    if not where_sql:
        return
    for row in db.execute(
        f"""
        SELECT custom_field_values.entity_type, custom_field_values.entity_id, custom_field_definitions.field_key, custom_field_values.value_json
        FROM custom_field_values
        JOIN custom_field_definitions
          ON custom_field_definitions.id = custom_field_values.field_id
         AND custom_field_definitions.entity_type = custom_field_values.entity_type
        WHERE custom_field_definitions.archived_at IS NULL
          AND {where_sql}
        ORDER BY custom_field_values.entity_type, custom_field_values.entity_id, custom_field_definitions.position, lower(custom_field_definitions.label)
        """,
        params,
    ).fetchall():
        record = records.get((str(row["entity_type"]), str(row["entity_id"])))
        if record is not None:
            record["custom_fields"][str(row["field_key"])] = json.loads(row["value_json"] or "null")


def _attach_records_table_connection_summaries(db: sqlite3.Connection, records: dict[tuple[str, str], dict[str, Any]]) -> None:
    summaries = connection_summaries_for_records(db, records.keys())
    for key, record in records.items():
        record["connection_summary"] = summaries.get(key, {})


def _records_table_entity_id_where(entity_column: str, id_column: str, records: dict[tuple[str, str], dict[str, Any]]) -> tuple[str, list[Any]]:
    ids_by_entity: dict[str, list[str]] = {}
    for entity_type, entity_id in records:
        ids_by_entity.setdefault(entity_type, []).append(entity_id)
    clauses: list[str] = []
    params: list[Any] = []
    for entity_type, entity_ids in sorted(ids_by_entity.items()):
        placeholders = ", ".join("?" for _ in entity_ids)
        clauses.append(f"({entity_column} = ? AND {id_column} IN ({placeholders}))")
        params.extend([entity_type, *entity_ids])
    return " OR ".join(clauses), params


def _records_table_envelope(entity_type: str, record: dict[str, Any], computed: dict[str, Any], display: dict[str, str]) -> dict[str, Any]:
    title = title_for_record(record)
    return {
        "entity_type": entity_type,
        "id": record["id"],
        "title": title,
        "record": record,
        "computed": computed,
        "display": display,
        "ref": {
            "entity_type": entity_type,
            "entity_id": record["id"],
            "app_page": f"{ENTITY_ROUTE_SEGMENTS[entity_type]}/{record['id']}",
        },
    }


def _custom_field_columns(db, entity_type: str) -> list[dict[str, str]]:
    params: list[Any] = []
    where = "archived_at IS NULL"
    if entity_type != "all":
        where += " AND entity_type = ?"
        params.append(entity_type)
    rows = db.execute(
        f"""
        SELECT entity_type, field_key, label
        FROM custom_field_definitions
        WHERE {where}
        ORDER BY entity_type, position, lower(label), field_key
        """,
        params,
    ).fetchall()
    columns: list[dict[str, str]] = []
    for row in rows:
        field_entity = str(row["entity_type"])
        field_key = str(row["field_key"])
        label = str(row["label"] or field_key)
        if entity_type == "all":
            columns.append({"key": f"custom:{field_entity}:{field_key}", "label": f"{_field_label(field_entity)} {label}"})
        else:
            columns.append({"key": f"custom:{field_key}", "label": label})
    return columns


def _field_label(key: str) -> str:
    return key.replace("_", " ").title()
