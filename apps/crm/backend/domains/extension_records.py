"""Validated, typed CRUD for generic CRM business extensions (never delivery)."""

import json
import re
from datetime import datetime

from entity_catalog import EXTENSIONS
from errors import ValidationError
from store import new_id, require_text, row_to_dict, utc_now, write_event
from .record_lifecycle import get_non_deleted_record, record_exists, reindex_record


def extension_schema():
    return {"ok": True, "entities": EXTENSIONS, "delivery_supported": False}


def validate_field(key, kind, value):
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 9_007_199_254_740_991:
            raise ValidationError(f"`{key}` must be a safe integer.")
    elif kind == "json":
        if not isinstance(value, dict):
            raise ValidationError(f"`{key}` must be an object.")
        try:
            json.dumps(value, allow_nan=False)
        except (ValueError, TypeError) as error:
            raise ValidationError(f"`{key}` must contain JSON values.") from error
    else:
        value = require_text({key: value}, key)
        if kind == "date" and value:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValidationError(f"`{key}` must be an ISO date or timestamp.") from error
    return value


def validate_extension(db, entity_type, record):
    spec = EXTENSIONS[entity_type]
    require_text(record, "title", required=True)
    for key in spec.get("required", []):
        require_text(record, key, required=True)
    active = not record.get("archived_at")
    for key, kind in spec["fields"].items():
        validate_field(key, kind, record[key])
        if kind.startswith("ref:") and record[key]:
            state = record_exists(db, kind[4:], record[key])
            if state not in ({"active"} if active else {"active", "archived"}):
                raise ValidationError(f"`{key}` must reference an existing {'active ' if active else ''}record.")
    if entity_type == "campaign" and record["status"] not in {"draft", "ready", "paused", "completed"}:
        raise ValidationError("Campaign status must be draft, ready, paused or completed; this action cannot send.")
    if entity_type in {"campaign_variant", "campaign_step"}:
        for field in ("weight", "position", "delay_hours"):
            if field in record and record[field] < 0:
                raise ValidationError(f"`{field}` cannot be negative.")
    if entity_type == "expense" and not re.fullmatch(r"[A-Z]{3}", record["currency"]):
        raise ValidationError("Currency must be a three-letter uppercase code.")
    if entity_type == "campaign_member":
        state = record_exists(db, record["record_type"], record["record_id"])
        if state not in ({"active"} if active else {"active", "archived"}):
            raise ValidationError("Campaign recipient must reference an existing CRM record.")
    for field, related_type in (("variant_id", "campaign_variant"), ("member_id", "campaign_member")):
        if record.get(field):
            parent = get_non_deleted_record(db, related_type, record[field])
            if parent["campaign_id"] != record["campaign_id"]:
                raise ValidationError(f"`{field}` belongs to another campaign.")
    if entity_type == "custom_object_definition":
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", record["object_key"]):
            raise ValidationError("Object key must be a lowercase identifier.")
        for key, kind in record["fields"].items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or kind not in {"text", "integer", "date", "json", "boolean", "number"}:
                raise ValidationError("Custom object fields require valid identifiers and supported types.")
    if entity_type == "custom_object_record":
        definition = get_non_deleted_record(db, "custom_object_definition", record["definition_id"])
        validate_object_values(definition["fields"], record["fields"])


def validate_object_values(schema, values):
    import math
    for key, value in values.items():
        kind = schema.get(key)
        if not kind:
            raise ValidationError(f"Unknown custom object field `{key}`.")
        if kind == "boolean":
            if not isinstance(value, bool):
                raise ValidationError(f"`{key}` must be boolean.")
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValidationError(f"`{key}` must be finite numeric data.")
        else:
            validate_field(key, kind, value)


def save_extension(db, payload, *, update=False, restore=False):
    entity = require_text(payload, "entity_type", required=True)
    if entity not in EXTENSIONS:
        raise ValidationError("Unsupported extension entity type.")
    spec = EXTENSIONS[entity]
    entity_id = require_text(payload, "id") or new_id(entity)
    existing = get_non_deleted_record(db, entity, entity_id) if update else None
    fields = {"title": "text", "body": "text", "owner_id": "text", "metadata": "json", **spec["fields"]}
    values = {}
    for key, kind in fields.items():
        default = {} if kind == "json" else 0 if kind == "integer" else ""
        default = spec.get("defaults", {}).get(key, default)
        values[key] = validate_field(key, kind, payload.get(key, existing.get(key, default) if existing else default))
    now = utc_now()
    values.update(id=entity_id, created_at=existing["created_at"] if existing else now, updated_at=now,
                  archived_at=existing.get("archived_at") if existing else None, deleted_at=None)
    if restore:
        for key in ("created_at", "updated_at", "archived_at"):
            if payload.get(key):
                values[key] = validate_field(key, "date", payload[key])
    validate_extension(db, entity, values)
    if entity == "custom_object_definition" and existing:
        for row in db.execute("SELECT fields_json FROM custom_object_records WHERE definition_id = ? AND deleted_at IS NULL", (entity_id,)):
            validate_object_values(values["fields"], json.loads(row[0]))
    stored = {(key + "_json" if fields.get(key) == "json" else key):
              json.dumps(value, sort_keys=True, allow_nan=False) if fields.get(key) == "json" else value
              for key, value in values.items()}
    columns = list(stored)
    if update:
        db.execute(f"UPDATE {spec['table']} SET {', '.join(f'{key} = ?' for key in columns)} WHERE id = ?", [*stored.values(), entity_id])
    else:
        db.execute(f"INSERT INTO {spec['table']} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", list(stored.values()))
    record = get_non_deleted_record(db, entity, entity_id)
    if not record.get("archived_at"):
        reindex_record(db, entity, record)
    write_event(db, f"{entity}.{'updated' if update else 'created'}", entity, entity_id)
    return record


def list_extensions(db, payload):
    from store import parse_limit
    entity = require_text(payload, "entity_type", required=True)
    if entity not in EXTENSIONS:
        raise ValidationError("Unsupported extension entity type.")
    spec = EXTENSIONS[entity]
    where, params = ["deleted_at IS NULL", "archived_at IS NULL"], []
    for key in ("campaign_id", "definition_id", "status"):
        if key in spec["fields"] and payload.get(key):
            where.append(f"{key} = ?")
            params.append(require_text(payload, key))
    query = require_text(payload, "query")
    if query:
        where.append("(title LIKE ? OR body LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    offset = payload.get("offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValidationError("Offset must be a nonnegative integer.")
    limit = parse_limit(payload)
    rows = db.execute(f"SELECT * FROM {spec['table']} WHERE {' AND '.join(where)} ORDER BY updated_at DESC, id LIMIT ? OFFSET ?", [*params, limit + 1, offset]).fetchall()
    return {"ok": True, "records": [{**row_to_dict(row), "entity_type": entity} for row in rows[:limit]],
            "has_more": len(rows) > limit, "next_offset": offset + limit if len(rows) > limit else None}
