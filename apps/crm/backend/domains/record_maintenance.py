"""CRM record archive, tagging, bulk update, and merge operations."""

from __future__ import annotations

import json
from typing import Any

from errors import ValidationError
from domains.record_lifecycle import ensure_no_dependents, get_non_deleted_record, reindex_record
from domains.record_mutations import _update_entity_record
from store import delete_fts, get_record, new_id, require_text, table_for_entity, utc_now, write_event


def archive_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    record = get_non_deleted_record(db, entity_type, entity_id)
    if record.get("archived_at"):
        return record
    table = table_for_entity(entity_type)
    now = utc_now()
    db.execute(f"UPDATE {table} SET archived_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, entity_id))
    delete_fts(db, entity_type, entity_id)
    write_event(db, f"{entity_type}.archived", entity_type, entity_id)
    return get_non_deleted_record(db, entity_type, entity_id)


def unarchive_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    get_non_deleted_record(db, entity_type, entity_id)
    table = table_for_entity(entity_type)
    now = utc_now()
    db.execute(f"UPDATE {table} SET archived_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, entity_id))
    record = get_record(db, entity_type, entity_id)
    reindex_record(db, entity_type, record)
    write_event(db, f"{entity_type}.unarchived", entity_type, entity_id)
    return record


def delete_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    get_non_deleted_record(db, entity_type, entity_id)
    ensure_no_dependents(db, entity_type, entity_id)
    table = table_for_entity(entity_type)
    now = utc_now()
    db.execute(f"UPDATE {table} SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, entity_id))
    db.execute("DELETE FROM record_tags WHERE record_type = ? AND record_id = ?", (entity_type, entity_id))
    delete_fts(db, entity_type, entity_id)
    write_event(db, f"{entity_type}.deleted", entity_type, entity_id)
    return {"ok": True, "entity_type": entity_type, "id": entity_id, "deleted_at": now}


def tag_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    name = require_text(payload, "tag") or require_text(payload, "name", required=True)
    color = require_text(payload, "color")
    get_non_deleted_record(db, entity_type, entity_id)
    now = utc_now()
    db.execute(
        "INSERT INTO tags(id, name, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET color = excluded.color, updated_at = excluded.updated_at",
        (new_id("tag"), name, color, now, now),
    )
    row = db.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ValidationError("CRM tag could not be resolved after upsert.")
    db.execute(
        "INSERT OR IGNORE INTO record_tags(record_type, record_id, tag_id, created_at) VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, str(row["id"]), now),
    )
    write_event(db, f"{entity_type}.tagged", entity_type, entity_id, {"tag": name})
    return get_non_deleted_record(db, entity_type, entity_id)


def untag_record(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id") or require_text(payload, "entity_id", required=True)
    name = require_text(payload, "tag") or require_text(payload, "name", required=True)
    get_non_deleted_record(db, entity_type, entity_id)
    db.execute(
        """
        DELETE FROM record_tags
        WHERE record_type = ? AND record_id = ? AND tag_id IN (SELECT id FROM tags WHERE name = ?)
        """,
        (entity_type, entity_id, name),
    )
    write_event(db, f"{entity_type}.untagged", entity_type, entity_id, {"tag": name})
    return get_non_deleted_record(db, entity_type, entity_id)


def bulk_update(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not all(isinstance(item, str) and item.strip() for item in ids):
        raise ValidationError("`ids` must be a non-empty array of record ids.")
    operation = require_text(payload, "operation", default="update") or "update"
    updated: list[dict[str, Any]] = []
    for entity_id in ids:
        item_payload = {**payload, "id": entity_id}
        if operation == "archive":
            updated.append(archive_record(db, item_payload))
        elif operation == "delete":
            delete_record(db, item_payload)
        elif operation == "tag":
            updated.append(tag_record(db, item_payload))
        elif operation == "update":
            updated.append(_update_entity_record(db, entity_type, {**(payload.get("changes") or {}), "id": entity_id}))
        else:
            raise ValidationError("Unsupported bulk operation.", details={"operation": operation})
    write_event(db, f"{entity_type}.bulk_{operation}", entity_type, "", {"ids": ids})
    return {"ok": True, "entity_type": entity_type, "operation": operation, "updated_count": len(ids), "records": updated}


def merge_records(db, payload: dict[str, Any]) -> dict[str, Any]:
    entity_type = require_text(payload, "entity_type", required=True)
    if entity_type not in {"lead", "account", "contact"}:
        raise ValidationError("CRM merge supports lead, account, and contact records.", details={"entity_type": entity_type})
    target_id = require_text(payload, "target_id", required=True)
    raw_source_ids = payload.get("source_ids")
    if raw_source_ids is None:
        raw_source_ids = [require_text(payload, "source_id", required=True)]
    if not isinstance(raw_source_ids, list):
        raise ValidationError("`source_ids` must be an array of record ids.")
    source_ids = []
    for source_id in raw_source_ids:
        normalized = str(source_id or "").strip()
        if not normalized:
            continue
        if normalized == target_id:
            raise ValidationError("A record cannot be merged into itself.", details={"target_id": target_id})
        if normalized not in source_ids:
            source_ids.append(normalized)
    if not source_ids:
        raise ValidationError("At least one source record is required.")
    target = get_record(db, entity_type, target_id)
    sources = [get_record(db, entity_type, source_id) for source_id in source_ids]
    field_overrides = payload.get("field_overrides") or {}
    if not isinstance(field_overrides, dict):
        raise ValidationError("`field_overrides` must be an object.")
    merged_payload = _merge_record_payload(entity_type, target, sources, field_overrides)
    updated_target = _update_entity_record(db, entity_type, {**merged_payload, "id": target_id}) if merged_payload else target
    now = utc_now()
    reassigned_counts: dict[str, int] = {}
    for source_id in source_ids:
        _merge_record_tags(db, entity_type, source_id, target_id, now)
        _merge_custom_field_values(db, entity_type, source_id, target_id, now)
        _merge_external_refs(db, entity_type, source_id, target_id, now)
        _merge_dependents(db, entity_type, source_id, target_id, now, reassigned_counts)
        _merge_metadata_refs(db, entity_type, source_id, target_id, now, reassigned_counts)
        table = table_for_entity(entity_type)
        db.execute(f"UPDATE {table} SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, source_id))
        delete_fts(db, entity_type, source_id)
        write_event(db, "record.merged", entity_type, source_id, {"target_id": target_id, "role": "source"})
    updated_target = get_record(db, entity_type, target_id)
    reindex_record(db, entity_type, updated_target)
    write_event(db, "record.merged", entity_type, target_id, {"source_ids": source_ids, "reassigned_counts": reassigned_counts, "role": "target"})
    return {"ok": True, "entity_type": entity_type, "target": updated_target, "merged_ids": source_ids, "reassigned_counts": reassigned_counts}


def _merge_record_payload(entity_type: str, target: dict[str, Any], sources: list[dict[str, Any]], overrides: dict[str, Any]) -> dict[str, Any]:
    fields_by_entity = {
        "lead": ("first_name", "last_name", "display_name", "email", "phone", "company", "domain", "source", "status", "owner_id", "summary", "account_id", "contact_id", "deal_id"),
        "account": ("name", "domain", "industry", "status", "owner_id", "summary"),
        "contact": ("account_id", "first_name", "last_name", "display_name", "email", "phone", "role", "owner_id", "summary"),
    }
    merged: dict[str, Any] = {}
    for field in fields_by_entity[entity_type]:
        if target.get(field) not in (None, ""):
            continue
        for source in sources:
            if source.get(field) not in (None, ""):
                merged[field] = source.get(field)
                break
    metadata_values = dict(target.get("metadata") if isinstance(target.get("metadata"), dict) else {})
    for source in sources:
        source_metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        for key, value in source_metadata.items():
            metadata_values.setdefault(key, value)
    if metadata_values != (target.get("metadata") if isinstance(target.get("metadata"), dict) else {}):
        merged["metadata"] = metadata_values
    for field, value in overrides.items():
        if field in fields_by_entity[entity_type] or field == "metadata":
            merged[str(field)] = value
    return merged


def _merge_record_tags(db, entity_type: str, source_id: str, target_id: str, now: str) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO record_tags(record_type, record_id, tag_id, created_at)
        SELECT record_type, ?, tag_id, ? FROM record_tags
        WHERE record_type = ? AND record_id = ?
        """,
        (target_id, now, entity_type, source_id),
    )
    db.execute("DELETE FROM record_tags WHERE record_type = ? AND record_id = ?", (entity_type, source_id))


def _merge_custom_field_values(db, entity_type: str, source_id: str, target_id: str, now: str) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO custom_field_values(entity_type, entity_id, field_id, value_json, updated_at)
        SELECT entity_type, ?, field_id, value_json, ? FROM custom_field_values
        WHERE entity_type = ? AND entity_id = ?
        """,
        (target_id, now, entity_type, source_id),
    )
    db.execute("DELETE FROM custom_field_values WHERE entity_type = ? AND entity_id = ?", (entity_type, source_id))


def _merge_external_refs(db, entity_type: str, source_id: str, target_id: str, now: str) -> None:
    db.execute(
        "UPDATE external_refs SET crm_entity_id = ?, updated_at = ? WHERE crm_entity_type = ? AND crm_entity_id = ? AND deleted_at IS NULL",
        (target_id, now, entity_type, source_id),
    )


def _merge_dependents(db, entity_type: str, source_id: str, target_id: str, now: str, counts: dict[str, int]) -> None:
    dependent_specs = {
        "account": (("contacts", "account_id"), ("deals", "account_id"), ("activities", "account_id"), ("tasks", "account_id"), ("notes", "account_id")),
        "contact": (("deals", "contact_id"), ("activities", "contact_id"), ("tasks", "contact_id"), ("notes", "contact_id")),
    }
    for table, field in dependent_specs.get(entity_type, ()):
        cursor = db.execute(
            f"UPDATE {table} SET {field} = ?, updated_at = ? WHERE {field} = ? AND deleted_at IS NULL",
            (target_id, now, source_id),
        )
        counts[f"{table}.{field}"] = counts.get(f"{table}.{field}", 0) + int(cursor.rowcount if cursor.rowcount is not None else 0)


def _merge_metadata_refs(db, entity_type: str, source_id: str, target_id: str, now: str, counts: dict[str, int]) -> None:
    metadata_key = f"{entity_type}_id"
    for table in ("activities", "tasks", "notes"):
        rows = db.execute(f"SELECT id, metadata_json FROM {table} WHERE deleted_at IS NULL AND metadata_json LIKE ?", (f"%{source_id}%",)).fetchall()
        changed = 0
        for row in rows:
            metadata_value = json.loads(str(row["metadata_json"] or "{}"))
            if not isinstance(metadata_value, dict):
                continue
            did_change = False
            if str(metadata_value.get(metadata_key) or "") == source_id:
                metadata_value[metadata_key] = target_id
                did_change = True
            nested = metadata_value.get("crm_ref")
            if isinstance(nested, dict) and nested.get("entity_type") == entity_type and nested.get("entity_id") == source_id:
                nested["entity_id"] = target_id
                did_change = True
            if did_change:
                db.execute(f"UPDATE {table} SET metadata_json = ?, updated_at = ? WHERE id = ?", (json.dumps(metadata_value, ensure_ascii=True, sort_keys=True), now, row["id"]))
                changed += 1
        if changed:
            counts[f"{table}.metadata_json"] = counts.get(f"{table}.metadata_json", 0) + changed
