"""One transactional import writer shared by simulation and apply."""

from entity_catalog import ENTITY_TABLES, EXTENSIONS
from errors import ValidationError
from store import row_to_dict
import sqlite3
from .export_records import upsert_export_record
from .export_restore import restore_export_payload, _upsert_workflow_proposal_export
from .extension_records import save_extension
from .import_sources import digest, source_record_id
from .record_graph import link_records

IMPORT_ORDER = ["custom_object_definition", "account", "contact", "lead", "deal", "conversation_thread",
                "task", "custom_object_record", "campaign", "campaign_variant", "campaign_step",
                "campaign_member", "campaign_event", "expense", "brief", "intelligence_profile",
                "activity", "note", "workflow_proposal"]


def resolve_identity(db, bundle, item):
    source_id, key, entity = bundle["source_id"], item["source_key"], item["entity_type"]
    identity = db.execute("SELECT * FROM import_identities WHERE source_id=? AND source_key=?", (source_id, key)).fetchone()
    if identity:
        if identity["entity_type"] != entity:
            raise ValidationError("Source identity cannot change entity type.")
        return identity["entity_id"], identity["fingerprint"]
    candidate_id = source_record_id(source_id, key)
    if entity == "workflow_proposal":
        return candidate_id, ""
    table = ENTITY_TABLES.get(entity)
    if not table:
        raise ValidationError("Unsupported import entity type.")
    if bundle["policy"] != "duplicate":
        match_field = "email" if entity in {"contact", "lead"} else "domain" if entity == "account" else ""
        match = str(item["record"].get(match_field) or "").strip().lower()
        if match:
            candidates = db.execute(f"SELECT id FROM {table} WHERE lower(trim({match_field}))=? AND deleted_at IS NULL AND archived_at IS NULL", (match,)).fetchall()
            if len(candidates) > 1:
                raise ValidationError("Multiple exact matches; resolve duplicates manually before import.")
            if candidates:
                candidate_id = candidates[0][0]
    return candidate_id, ""


def write_row(db, bundle, item, identity, ids):
    entity, entity_id = item["entity_type"], identity[0]
    record = dict(item["record"])
    for field, key in item.get("foreign", {}).items():
        target = ids.get(key)
        if target is None:
            existing = db.execute("SELECT entity_type, entity_id FROM import_identities WHERE source_id=? AND source_key=?", (bundle["source_id"], key)).fetchone()
            target = tuple(existing) if existing else None
        if target is None:
            raise ValidationError(f"Missing source relationship `{key}`.")
        record[field] = target[1]
    if entity not in EXTENSIONS and entity != "workflow_proposal":
        columns = {row["name"].removesuffix("_json") for row in db.execute(f"PRAGMA table_info({ENTITY_TABLES[entity]})")}
        extras = {key: value for key, value in record.items() if key not in columns and key not in {"tags", "custom_fields", "entity_type"}}
        if extras:
            record["metadata"] = {**(record.get("metadata") or {}), "import_fields": extras}
    fingerprint = digest([bundle["policy"], record])
    table = "workflow_proposals" if entity == "workflow_proposal" else ENTITY_TABLES[entity]
    found = db.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone()
    current = row_to_dict(found) if found else None
    if current and (current.get("deleted_at") or current.get("archived_at")):
        raise ValidationError("Import target is inactive; explicit lifecycle review is required.")
    if current and bundle["policy"] == "manual":
        raise ValidationError("Conflict requires manual review; choose a resolution policy after reviewing the record.")
    outcome = "created"
    if current and (identity[1] == fingerprint or bundle["policy"] in {"skip", "duplicate"}):
        outcome = "skipped"
        # A skipped row is not an applied source version: a later explicit
        # overwrite/fill policy must still be able to reconcile that source.
        fingerprint = identity[1]
    else:
        if current:
            outcome = "updated"
            if bundle["policy"] == "fill_empty":
                record = {**current, **{key: value for key, value in record.items() if current.get(key) in (None, "", {}, [])}}
            else:
                record = {**current, **record}
        record["id"] = entity_id
        if entity in EXTENSIONS:
            save_extension(db, {**record, "entity_type": entity}, update=bool(current), restore=True)
        elif entity == "workflow_proposal":
            # Imported suggestions authorize only a review task, never source-provided code/actions.
            _upsert_workflow_proposal_export(db, {"id": entity_id, "title": record["title"], "proposal_type": "data_quality_review",
                "status": "pending", "entity_type": "task", "entity_id": entity_id, "source": bundle["source_id"],
                "proposal": {"action": {"type": "create_task", "title": record["title"], "body": record.get("body", "")},
                             "source_evidence": record.get("metadata", {})}})
        else:
            upsert_export_record(db, entity, record)
        if record.get("custom_fields"):
            from .custom_fields import set_custom_fields
            set_custom_fields(db, {"entity_type": entity, "id": entity_id, "custom_fields": record["custom_fields"]})
        if record.get("tags"):
            from .record_maintenance import tag_record
            tags = record["tags"]
            if not isinstance(tags, list):
                raise ValidationError("Import tags must be an array.")
            for tag in tags:
                name = tag.get("name") if isinstance(tag, dict) else tag
                tag_record(db, {"entity_type": entity, "id": entity_id, "tag": name})
    db.execute("INSERT INTO import_identities VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_id, source_key) DO UPDATE SET fingerprint=excluded.fingerprint",
               (bundle["source_id"], item["source_key"], entity, entity_id, fingerprint))
    return {"entity_type": entity, "entity_id": entity_id, "source_key": item["source_key"], "outcome": outcome}


def write_bundle(db, bundle):
    if "native_export" in bundle:
        result = restore_export_payload(db, bundle["native_export"])
        return {"ok": True, "created_count": result["created_count"], "updated_count": result["updated_count"],
                "skipped_count": 0, "row_count": len(result["records"]), "rows": [], "errors": [], "warnings": bundle["warnings"]}
    records = bundle["records"]
    if any(item["entity_type"] not in IMPORT_ORDER for item in records):
        raise ValidationError("Unsupported import entity type.")
    seen = {}
    for item in records:
        fingerprint = digest(item)
        if item["source_key"] in seen and seen[item["source_key"]] != fingerprint:
            raise ValidationError("A source key has conflicting rows in the same batch.")
        seen[item["source_key"]] = fingerprint
    ordered = sorted(enumerate(records, 1), key=lambda pair: IMPORT_ORDER.index(pair[1]["entity_type"]))
    ids, outcomes, errors = {}, [], []
    for index, item in ordered:
        db.execute("SAVEPOINT import_row")
        try:
            identity = resolve_identity(db, bundle, item)
            ids[item["source_key"]] = (item["entity_type"], identity[0])
            outcome = write_row(db, bundle, item, identity, ids)
            outcomes.append({"row": index, **outcome})
        except (ValidationError, ValueError, TypeError, sqlite3.IntegrityError) as error:
            db.execute("ROLLBACK TO import_row")
            errors.append({"row": index, "source_key": item["source_key"], "errors": [str(error)]})
        finally:
            db.execute("RELEASE import_row")
    for index, link in enumerate(bundle.get("links", []), len(records) + 1):
        try:
            endpoints = []
            for prefix in ("source", "target"):
                key = link[f"{prefix}_key"]
                endpoint = ids.get(key)
                if not endpoint:
                    row = db.execute("SELECT entity_type, entity_id FROM import_identities WHERE source_id=? AND source_key=?", (bundle["source_id"], key)).fetchone()
                    endpoint = tuple(row) if row else None
                if not endpoint:
                    raise ValidationError(f"Missing source relationship `{key}`.")
                endpoints.append(endpoint)
            if endpoints[0] != endpoints[1]:
                link_records(db, {"source_type": endpoints[0][0], "source_id": endpoints[0][1], "target_type": endpoints[1][0], "target_id": endpoints[1][1], "relationship": link["relationship"]})
        except ValidationError as error:
            errors.append({"row": index, "errors": [str(error)]})
    return {"ok": not errors, "row_count": len(records), "rows": sorted(outcomes, key=lambda row: row["row"]),
            **{f"{name}_count": sum(row["outcome"] == name for row in outcomes) for name in ("created", "updated", "skipped")},
            "errors": errors, "warnings": bundle["warnings"], "relationship_count": len(bundle.get("links", []))}
