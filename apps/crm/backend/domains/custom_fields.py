"""Custom field schema and value operations for CRM records."""

from __future__ import annotations

import json
import math
from typing import Any

from errors import NotFoundError, ValidationError
from store import (
    CUSTOM_FIELD_TYPES,
    SCHEMA_VERSION,
    get_record,
    new_id,
    require_text,
    row_to_dict,
    table_for_entity,
    utc_now,
    write_event,
)

from .record_lifecycle import record_exists, reindex_record


ENTITY_TABLES = {
    "lead": "leads",
    "account": "accounts",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "task": "tasks",
    "note": "notes",
}
FIELD_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


def schema_config(db) -> dict[str, Any]:
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "entities": {entity_type: {"table": table, "standard_fields": _standard_fields_for_entity(entity_type)} for entity_type, table in ENTITY_TABLES.items()},
        "custom_fields": list_custom_fields(db, "all"),
        "custom_field_types": sorted(CUSTOM_FIELD_TYPES),
        "pipelines": [row_to_dict(row) for row in db.execute("SELECT * FROM pipelines ORDER BY name").fetchall()],
        "pipeline_stages": [row_to_dict(row) for row in db.execute("SELECT * FROM pipeline_stages ORDER BY pipeline_id, position").fetchall()],
        "automation_rules": [row_to_dict(row) for row in db.execute("SELECT * FROM automation_rules ORDER BY updated_at DESC").fetchall()],
    }


def _standard_fields_for_entity(entity_type: str) -> list[dict[str, str]]:
    fields = {
        "lead": ["display_name", "email", "phone", "company", "domain", "source", "status", "owner_id", "summary"],
        "account": ["name", "domain", "industry", "status", "owner_id", "summary"],
        "contact": ["display_name", "email", "phone", "role", "account_id", "owner_id", "summary"],
        "deal": ["name", "account_id", "contact_id", "stage_id", "value", "currency", "probability", "close_date", "owner_id", "summary"],
        "activity": ["activity_type", "subject", "body", "account_id", "contact_id", "deal_id", "occurred_at", "due_at", "completed_at", "owner_id"],
        "task": ["title", "status", "priority", "due_at", "account_id", "contact_id", "deal_id", "owner_id", "body"],
        "note": ["body", "account_id", "contact_id", "deal_id", "owner_id"],
    }
    return [{"key": key, "label": key.replace("_", " ").title()} for key in fields.get(entity_type, [])]


def list_custom_fields(db, entity_type: str = "all") -> list[dict[str, Any]]:
    if entity_type and entity_type != "all":
        table_for_entity(entity_type)
        rows = db.execute(
            "SELECT * FROM custom_field_definitions WHERE entity_type = ? AND archived_at IS NULL ORDER BY position, lower(label)",
            (entity_type,),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM custom_field_definitions WHERE archived_at IS NULL ORDER BY entity_type, position, lower(label)").fetchall()
    return [_custom_field_from_row(row) for row in rows]


def define_custom_field(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    table_for_entity(entity_type)
    field_key = _normalize_field_key(require_text(payload, "field_key") or require_text(payload, "key", required=True))
    label = require_text(payload, "label") or field_key.replace("_", " ").title()
    field_type = require_text(payload, "field_type", default="text") or "text"
    if field_type not in CUSTOM_FIELD_TYPES:
        raise ValidationError("Unsupported custom field type.", details={"field_type": field_type, "supported": sorted(CUSTOM_FIELD_TYPES)})
    options = payload.get("options") or []
    if field_type in {"select", "multi_select"}:
        if not isinstance(options, list) or not all(isinstance(item, str) and item.strip() for item in options):
            raise ValidationError("Select custom fields require `options` as a non-empty string array.")
        options = [item.strip() for item in options]
    elif options:
        raise ValidationError("Only select custom fields can declare options.")
    default_value = _coerce_custom_field_value({"field_key": field_key, "field_type": field_type, "options": options, "required": False}, payload.get("default_value")) if "default_value" in payload else None
    now = utc_now()
    field_id = require_text(payload, "id") or new_id("field")
    db.execute(
        """
        INSERT INTO custom_field_definitions(id, entity_type, field_key, label, field_type, required, options_json, default_value_json, position, created_at, updated_at, archived_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(entity_type, field_key) DO UPDATE SET label = excluded.label, field_type = excluded.field_type,
          required = excluded.required, options_json = excluded.options_json, default_value_json = excluded.default_value_json,
          position = excluded.position, updated_at = excluded.updated_at, archived_at = NULL
        """,
        (
            field_id,
            entity_type,
            field_key,
            label,
            field_type,
            1 if bool(payload.get("required")) else 0,
            json.dumps(options, ensure_ascii=True),
            json.dumps(default_value, ensure_ascii=True),
            int(_coerce_number(payload, "position", 0)),
            now,
            now,
        ),
    )
    row = db.execute("SELECT * FROM custom_field_definitions WHERE entity_type = ? AND field_key = ?", (entity_type, field_key)).fetchone()
    write_event(db, "custom_field.defined", entity_type, field_key)
    return _custom_field_from_row(row)


def archive_custom_field(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    field_key = _normalize_field_key(require_text(payload, "field_key") or require_text(payload, "key", required=True))
    field = _custom_field_definition(db, entity_type, field_key)
    now = utc_now()
    db.execute("UPDATE custom_field_definitions SET archived_at = ?, updated_at = ? WHERE id = ?", (now, now, field["id"]))
    write_event(db, "custom_field.archived", entity_type, field_key)
    return _custom_field_from_row(db.execute("SELECT * FROM custom_field_definitions WHERE id = ?", (field["id"],)).fetchone())


def set_custom_fields(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    get_record(db, entity_type, entity_id)
    values = payload.get("custom_fields") or payload.get("values") or {}
    if not isinstance(values, dict):
        raise ValidationError("`custom_fields` must be an object.")
    fields = {field["field_key"]: field for field in list_custom_fields(db, entity_type)}
    unknown = sorted(str(key) for key in values if str(key) not in fields)
    if unknown:
        raise ValidationError("Unknown custom field key.", details={"entity_type": entity_type, "keys": unknown})
    now = utc_now()
    for key, raw_value in values.items():
        field = fields[str(key)]
        value = _coerce_custom_field_value(field, raw_value)
        db.execute(
            """
            INSERT INTO custom_field_values(entity_type, entity_id, field_id, value_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, entity_id, field_id) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (entity_type, entity_id, field["id"], json.dumps(value, ensure_ascii=True), now),
        )
    table = table_for_entity(entity_type)
    db.execute(f"UPDATE {table} SET updated_at = ? WHERE id = ?", (now, entity_id))
    updated = get_record(db, entity_type, entity_id)
    reindex_record(db, entity_type, updated)
    write_event(db, f"{entity_type}.custom_fields.updated", entity_type, entity_id, {"keys": sorted(values.keys())})
    return updated


def _upsert_custom_field_definition_export(db, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    field_id = require_text(row, "id") or new_id("field")
    entity_type = require_text(row, "entity_type", required=True)
    field_key = _normalize_field_key(require_text(row, "field_key", required=True))
    exists = db.execute("SELECT 1 FROM custom_field_definitions WHERE id = ? OR (entity_type = ? AND field_key = ?)", (field_id, entity_type, field_key)).fetchone() is not None
    db.execute(
        """
        INSERT INTO custom_field_definitions(id, entity_type, field_key, label, field_type, required, options_json, default_value_json, position, created_at, updated_at, archived_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, field_key) DO UPDATE SET label = excluded.label, field_type = excluded.field_type,
          required = excluded.required, options_json = excluded.options_json, default_value_json = excluded.default_value_json,
          position = excluded.position, updated_at = excluded.updated_at, archived_at = excluded.archived_at
        """,
        (
            field_id,
            entity_type,
            field_key,
            require_text(row, "label") or field_key,
            require_text(row, "field_type", default="text") or "text",
            1 if bool(row.get("required")) else 0,
            json.dumps(row.get("options") if isinstance(row.get("options"), list) else [], ensure_ascii=True),
            json.dumps(row.get("default_value"), ensure_ascii=True),
            int(_coerce_number(row, "position", 0)),
            require_text(row, "created_at") or utc_now(),
            require_text(row, "updated_at") or utc_now(),
            require_text(row, "archived_at") or None,
        ),
    )
    return (_custom_field_from_row(db.execute("SELECT * FROM custom_field_definitions WHERE entity_type = ? AND field_key = ?", (entity_type, field_key)).fetchone()), not exists)


def _upsert_custom_field_value_export(db, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    entity_type = require_text(row, "entity_type", required=True)
    entity_id = require_text(row, "entity_id", required=True)
    field_id = require_text(row, "field_id", required=True)
    exists = db.execute("SELECT 1 FROM custom_field_values WHERE entity_type = ? AND entity_id = ? AND field_id = ?", (entity_type, entity_id, field_id)).fetchone() is not None
    field_exists = db.execute("SELECT 1 FROM custom_field_definitions WHERE id = ? AND entity_type = ?", (field_id, entity_type)).fetchone() is not None
    if not field_exists:
        raise ValidationError("Custom field value references an unknown field definition.", details={"entity_type": entity_type, "entity_id": entity_id, "field_id": field_id})
    state = record_exists(db, entity_type, entity_id)
    if state in {"", "deleted"}:
        raise ValidationError("Custom field value references a missing CRM record.", details={"entity_type": entity_type, "entity_id": entity_id, "state": state or "missing"})
    db.execute(
        """
        INSERT INTO custom_field_values(entity_type, entity_id, field_id, value_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id, field_id) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
        """,
        (entity_type, entity_id, field_id, json.dumps(row.get("value"), ensure_ascii=True), require_text(row, "updated_at") or utc_now()),
    )
    if state == "active":
        updated = get_record(db, entity_type, entity_id)
        reindex_record(db, entity_type, updated)
    return ({"entity_type": entity_type, "entity_id": entity_id, "field_id": field_id, "value": row.get("value")}, not exists)


def _custom_field_from_row(row) -> dict[str, Any]:
    item = row_to_dict(row)
    item["required"] = bool(item.get("required"))
    return item


def _normalize_field_key(value: str) -> str:
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not key or any(char not in FIELD_KEY_CHARS for char in key):
        raise ValidationError("Custom field key must contain only lowercase letters, numbers, and underscores.", details={"field_key": value})
    return key


def _custom_field_definition(db, entity_type: str, field_key: str) -> dict[str, Any]:
    table_for_entity(entity_type)
    row = db.execute(
        "SELECT * FROM custom_field_definitions WHERE entity_type = ? AND field_key = ? AND archived_at IS NULL",
        (entity_type, field_key),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"custom_field `{entity_type}.{field_key}` was not found.")
    return _custom_field_from_row(row)


def _coerce_custom_field_value(field: dict[str, Any], raw_value: Any) -> Any:
    field_type = str(field.get("field_type") or "text")
    required = bool(field.get("required"))
    if raw_value in (None, ""):
        if required:
            raise ValidationError("Required custom field cannot be empty.", details={"field_key": field.get("field_key")})
        return None
    if field_type in {"text", "url", "email", "date"}:
        value = str(raw_value).strip()
        if field_type == "email" and value and "@" not in value:
            raise ValidationError("Email custom field must contain an email-like value.", details={"field_key": field.get("field_key")})
        return value
    if field_type == "number":
        try:
            number = float(raw_value)
        except (TypeError, ValueError) as error:
            raise ValidationError("Number custom field must be numeric.", details={"field_key": field.get("field_key")}) from error
        if not math.isfinite(number):
            raise ValidationError("Number custom field must be finite.", details={"field_key": field.get("field_key")})
        return number
    if field_type == "boolean":
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str) and raw_value.lower() in {"true", "1", "yes", "y"}:
            return True
        if isinstance(raw_value, str) and raw_value.lower() in {"false", "0", "no", "n"}:
            return False
        raise ValidationError("Boolean custom field must be true or false.", details={"field_key": field.get("field_key")})
    options = field.get("options") if isinstance(field.get("options"), list) else []
    if field_type == "select":
        value = str(raw_value).strip()
        if value not in options:
            raise ValidationError("Select custom field value is not in options.", details={"field_key": field.get("field_key"), "options": options})
        return value
    if field_type == "multi_select":
        if not isinstance(raw_value, list):
            raise ValidationError("Multi-select custom field value must be an array.", details={"field_key": field.get("field_key")})
        values = [str(item).strip() for item in raw_value if str(item).strip()]
        unknown = sorted(set(values) - set(options))
        if unknown:
            raise ValidationError("Multi-select custom field values are not in options.", details={"field_key": field.get("field_key"), "unknown": unknown})
        return values
    raise ValidationError("Unsupported custom field type.", details={"field_type": field_type})


def _coerce_number(payload: dict[str, Any], key: str, default: float) -> float:
    value = payload.get(key, default)
    if value is None or value == "":
        return float(default)
    if isinstance(value, bool):
        raise ValidationError(f"`{key}` must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"`{key}` must be a number.") from error
    if not math.isfinite(number):
        raise ValidationError(f"`{key}` must be a finite number.")
    return number
