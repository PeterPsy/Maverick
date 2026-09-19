"""CRM-owned relationship graph; provider data stays behind external references."""

from entity_catalog import EXTENSIONS
from errors import ValidationError
from store import get_record, new_id, require_text, row_to_dict, utc_now, write_event
from .external_refs import list_external_refs
from .record_lifecycle import get_non_deleted_record, record_exists


def link_records(db, payload, *, historical=False):
    values = {key: require_text(payload, key, required=True)
              for key in ("source_type", "source_id", "target_type", "target_id")}
    relationship = require_text(payload, "relationship", default="related") or "related"
    if len(relationship) > 80:
        raise ValidationError("Relationship labels must be at most 80 characters.")
    for prefix in ("source", "target"):
        state = record_exists(db, values[f"{prefix}_type"], values[f"{prefix}_id"])
        if state not in ({"active", "archived"} if historical else {"active"}):
            raise ValidationError("Both link endpoints must exist and be active.")
    if (values["source_type"], values["source_id"]) == (values["target_type"], values["target_id"]):
        raise ValidationError("A CRM record cannot link to itself.")
    args = [*values.values(), relationship]
    existing = db.execute("SELECT * FROM record_links WHERE source_type=? AND source_id=? AND target_type=? AND target_id=? AND relationship=?", args).fetchone()
    if existing:
        return row_to_dict(existing)
    entity_id = require_text(payload, "id") or new_id("link")
    db.execute("INSERT INTO record_links VALUES (?, ?, ?, ?, ?, ?, ?)", [entity_id, *args, utc_now()])
    write_event(db, "record.linked", values["source_type"], values["source_id"], values)
    return row_to_dict(db.execute("SELECT * FROM record_links WHERE id=?", (entity_id,)).fetchone())


def unlink_records(db, payload):
    entity_id = require_text(payload, "id", required=True)
    row = db.execute("SELECT * FROM record_links WHERE id=?", (entity_id,)).fetchone()
    if row:
        db.execute("DELETE FROM record_links WHERE id=?", (entity_id,))
        write_event(db, "record.unlinked", row["source_type"], row["source_id"], {"link_id": entity_id})
    return {"ok": True, "unlinked": bool(row)}


def record_context(db, payload):
    entity = require_text(payload, "entity_type", required=True)
    entity_id = require_text(payload, "id", required=True)
    record = get_record(db, entity, entity_id)
    rows = db.execute("SELECT * FROM record_links WHERE (source_type=? AND source_id=?) OR (target_type=? AND target_id=?) ORDER BY created_at, id", (entity, entity_id, entity, entity_id)).fetchall()
    links = []
    for row in rows:
        link = row_to_dict(row)
        prefix = "target" if (row["source_type"], row["source_id"]) == (entity, entity_id) else "source"
        target = get_non_deleted_record(db, row[f"{prefix}_type"], row[f"{prefix}_id"])
        links.append({**link, "record": target})
    return {"ok": True, "record": record, "links": links,
            "external_refs": list_external_refs(db, {"entity_type": entity, "entity_id": entity_id})}


def extension_dependents(db, entity, entity_id, *, active_only=False):
    counts = {}
    visibility = " AND archived_at IS NULL" if active_only else ""
    for kind, spec in EXTENSIONS.items():
        for field, field_kind in spec["fields"].items():
            if field_kind == f"ref:{entity}":
                counts[f"{kind}.{field}"] = db.execute(f"SELECT count(*) FROM {spec['table']} WHERE {field}=? AND deleted_at IS NULL{visibility}", (entity_id,)).fetchone()[0]
    counts["record_links"] = db.execute("SELECT count(*) FROM record_links WHERE (source_type=? AND source_id=?) OR (target_type=? AND target_id=?)", (entity, entity_id, entity, entity_id)).fetchone()[0]
    counts["campaign_members"] = db.execute(f"SELECT count(*) FROM campaign_members WHERE record_type=? AND record_id=? AND deleted_at IS NULL{visibility}", (entity, entity_id)).fetchone()[0]
    return counts


def merge_graph(db, entity, source_id, target_id):
    rows = db.execute("SELECT * FROM record_links WHERE (source_type=? AND source_id=?) OR (target_type=? AND target_id=?)", (entity, source_id, entity, source_id)).fetchall()
    for row in rows:
        payload = dict(row)
        db.execute("DELETE FROM record_links WHERE id=?", (row["id"],))
        for prefix in ("source", "target"):
            if payload[f"{prefix}_type"] == entity and payload[f"{prefix}_id"] == source_id:
                payload[f"{prefix}_id"] = target_id
        if (payload["source_type"], payload["source_id"]) != (payload["target_type"], payload["target_id"]):
            link_records(db, payload, historical=True)
    # Conflicting campaign enrollments need explicit review, not lossy deletion.
    db.execute("UPDATE campaign_members SET record_id=? WHERE record_type=? AND record_id=?", (target_id, entity, source_id))
    for spec in EXTENSIONS.values():
        for field, kind in spec["fields"].items():
            if kind == f"ref:{entity}":
                db.execute(f"UPDATE {spec['table']} SET {field}=? WHERE {field}=?", (target_id, source_id))
    db.execute("UPDATE import_identities SET entity_id=? WHERE entity_type=? AND entity_id=?", (target_id, entity, source_id))
