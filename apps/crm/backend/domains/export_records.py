"""CRM record restore operations for exported payloads."""

from __future__ import annotations

import json
import math
from typing import Any

from errors import ValidationError
from store import attach_tags, delete_fts, require_text, row_to_dict, utc_now, write_event

from .pipeline import _require_pipeline, _stage_name, _stage_probability
from .record_lifecycle import record_exists, reindex_record


TABLE_ENTITY_TYPES = {
    "leads": "lead",
    "accounts": "account",
    "contacts": "contact",
    "deals": "deal",
    "activities": "activity",
    "tasks": "task",
    "notes": "note",
}


def upsert_export_record(db, entity_type: str, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    record_id = require_text(row, "id", required=True)
    state = record_exists(db, entity_type, record_id)
    _validate_export_row_relationships(db, entity_type, row)
    return (_write_export_record(db, entity_type, row), not state)


def _write_export_record(db, entity_type: str, row: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    created_at = require_text(row, "created_at") or now
    updated_at = require_text(row, "updated_at") or now
    archived_at = require_text(row, "archived_at") or None
    deleted_at = require_text(row, "deleted_at") or None
    metadata_json = json.dumps(row.get("metadata") if isinstance(row.get("metadata"), dict) else {}, ensure_ascii=True, sort_keys=True)
    common_lifecycle = {"created_at": created_at, "updated_at": updated_at, "archived_at": archived_at, "deleted_at": deleted_at}

    if entity_type == "account":
        values = {
            "id": require_text(row, "id", required=True),
            "name": require_text(row, "name", required=True),
            "domain": require_text(row, "domain"),
            "industry": require_text(row, "industry"),
            "status": require_text(row, "status", default="prospect") or "prospect",
            "owner_id": require_text(row, "owner_id"),
            "summary": require_text(row, "summary"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "accounts", values)
    elif entity_type == "lead":
        first_name = require_text(row, "first_name")
        last_name = require_text(row, "last_name")
        display_name = require_text(row, "display_name") or " ".join(part for part in [first_name, last_name] if part) or require_text(row, "email", required=True)
        values = {
            "id": require_text(row, "id", required=True),
            "first_name": first_name,
            "last_name": last_name,
            "display_name": display_name,
            "email": require_text(row, "email"),
            "phone": require_text(row, "phone"),
            "company": require_text(row, "company"),
            "domain": require_text(row, "domain"),
            "source": require_text(row, "source"),
            "status": require_text(row, "status", default="new") or "new",
            "owner_id": require_text(row, "owner_id"),
            "summary": require_text(row, "summary"),
            "metadata_json": metadata_json,
            "converted_at": require_text(row, "converted_at"),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "deal_id": require_text(row, "deal_id"),
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "leads", values)
    elif entity_type == "contact":
        first_name = require_text(row, "first_name")
        last_name = require_text(row, "last_name")
        display_name = require_text(row, "display_name") or " ".join(part for part in [first_name, last_name] if part) or require_text(row, "email", required=True)
        values = {
            "id": require_text(row, "id", required=True),
            "account_id": require_text(row, "account_id"),
            "first_name": first_name,
            "last_name": last_name,
            "display_name": display_name,
            "email": require_text(row, "email"),
            "phone": require_text(row, "phone"),
            "role": require_text(row, "role"),
            "owner_id": require_text(row, "owner_id"),
            "summary": require_text(row, "summary"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "contacts", values)
    elif entity_type == "deal":
        pipeline_id = require_text(row, "pipeline_id", default="pipeline_default") or "pipeline_default"
        _require_pipeline(db, pipeline_id)
        stage_id = require_text(row, "stage_id", default=require_text(row, "stage", default="lead")) or "lead"
        values = {
            "id": require_text(row, "id", required=True),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "pipeline_id": pipeline_id,
            "stage_id": stage_id,
            "name": require_text(row, "name", required=True),
            "stage": _stage_name(db, stage_id, pipeline_id),
            "value": _coerce_number(row, "value", 0),
            "currency": require_text(row, "currency", default="EUR") or "EUR",
            "probability": _coerce_number(row, "probability", _stage_probability(db, stage_id, pipeline_id)),
            "close_date": require_text(row, "close_date"),
            "owner_id": require_text(row, "owner_id"),
            "summary": require_text(row, "summary"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "deals", values)
    elif entity_type == "activity":
        values = {
            "id": require_text(row, "id", required=True),
            "activity_type": require_text(row, "activity_type", default="note") or "note",
            "subject": require_text(row, "subject", required=True),
            "body": require_text(row, "body"),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "deal_id": require_text(row, "deal_id"),
            "occurred_at": require_text(row, "occurred_at", default=now) or now,
            "due_at": require_text(row, "due_at"),
            "completed_at": require_text(row, "completed_at"),
            "owner_id": require_text(row, "owner_id"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "activities", values)
    elif entity_type == "task":
        values = {
            "id": require_text(row, "id", required=True),
            "title": require_text(row, "title", required=True),
            "status": require_text(row, "status", default="open") or "open",
            "priority": require_text(row, "priority", default="normal") or "normal",
            "due_at": require_text(row, "due_at"),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "deal_id": require_text(row, "deal_id"),
            "owner_id": require_text(row, "owner_id"),
            "body": require_text(row, "body"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "tasks", values)
    elif entity_type == "note":
        values = {
            "id": require_text(row, "id", required=True),
            "body": require_text(row, "body", required=True),
            "account_id": require_text(row, "account_id"),
            "contact_id": require_text(row, "contact_id"),
            "deal_id": require_text(row, "deal_id"),
            "owner_id": require_text(row, "owner_id"),
            "metadata_json": metadata_json,
            **common_lifecycle,
        }
        record = _upsert_export_table_row(db, "notes", values)
    else:
        raise ValidationError("Unsupported entity_type.", details={"entity_type": entity_type})

    if record.get("deleted_at") or record.get("archived_at"):
        delete_fts(db, entity_type, str(record["id"]))
    else:
        reindex_record(db, entity_type, record)
    write_event(db, f"{entity_type}.imported", entity_type, str(record["id"]))
    return record


def _upsert_export_table_row(db, table: str, values: dict[str, Any]) -> dict[str, Any]:
    columns = list(values.keys())
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "id")
    db.execute(
        f"""
        INSERT INTO {table}({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {updates}
        """,
        tuple(values[column] for column in columns),
    )
    entity_type = TABLE_ENTITY_TYPES[table]
    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (values["id"],)).fetchone()
    record = row_to_dict(row)
    record["entity_type"] = entity_type
    return attach_tags(db, entity_type, record)


def _validate_export_row_relationships(db, entity_type: str, row: dict[str, Any]) -> None:
    fields_by_entity = {
        "contact": ("account_id",),
        "deal": ("account_id", "contact_id"),
        "activity": ("account_id", "contact_id", "deal_id"),
        "task": ("account_id", "contact_id", "deal_id"),
        "note": ("account_id", "contact_id", "deal_id"),
    }
    fields = fields_by_entity.get(entity_type, ())
    if not fields:
        return
    row_is_active = not require_text(row, "archived_at") and not require_text(row, "deleted_at")
    mapping = {"account_id": "account", "contact_id": "contact", "deal_id": "deal"}
    for field in fields:
        entity_id = require_text(row, field)
        if not entity_id:
            continue
        state = record_exists(db, mapping[field], entity_id)
        if row_is_active and state != "active":
            raise ValidationError("Active CRM records cannot link to inactive related records.", details={"field": field, "id": entity_id, "state": state or "missing"})
        if not row_is_active and state in {"", "deleted"}:
            raise ValidationError("Related CRM record was not found.", details={"field": field, "id": entity_id, "state": state or "missing"})


def _coerce_number(payload: dict[str, Any], key: str, default: float) -> float:
    value = payload.get(key, default)
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"`{key}` must be numeric.", details={key: value}) from error
    if not math.isfinite(number):
        raise ValidationError(f"`{key}` must be finite.", details={key: value})
    return number
