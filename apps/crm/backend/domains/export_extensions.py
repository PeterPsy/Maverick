"""Restore typed extensions and the configuration necessary for native round trips."""

import json

from entity_catalog import EXTENSIONS
from errors import ValidationError
from store import utc_now
from .extension_records import save_extension
from .record_graph import link_records
from .record_lifecycle import record_exists

CONFIG_TABLES = ("pipelines", "pipeline_stages", "tags", "record_tags", "saved_views")


def restore_configuration(db, payload, tables):
    for table in tables:
        if table not in CONFIG_TABLES:
            raise ValidationError("Unknown configuration table.")
        info = db.execute(f"PRAGMA table_info({table})").fetchall()
        primary = [row["name"] for row in info if row["pk"]]
        for row in payload.get(table, []):
            if not isinstance(row, dict):
                raise ValidationError(f"`{table}` must contain objects.")
            values = {}
            for column in info:
                name = column["name"]
                key = name[:-5] if name.endswith("_json") else name
                if key in row:
                    values[name] = json.dumps(row[key], allow_nan=False) if name.endswith("_json") else row[key]
            if not all(values.get(key) not in (None, "") for key in primary):
                raise ValidationError(f"`{table}` is missing its identity.")
            if table == "pipeline_stages" and not db.execute("SELECT 1 FROM pipelines WHERE id=?", (values.get("pipeline_id"),)).fetchone():
                raise ValidationError("Imported stage references a missing pipeline.")
            if table == "record_tags":
                if not record_exists(db, values["record_type"], values["record_id"]):
                    raise ValidationError("Imported tag references a missing record.")
                if not db.execute("SELECT 1 FROM tags WHERE id=?", (values["tag_id"],)).fetchone():
                    raise ValidationError("Imported tag definition is missing.")
            for key in ("created_at", "updated_at"):
                if any(c["name"] == key for c in info):
                    values.setdefault(key, utc_now())
            assignments = [f"{key}=excluded.{key}" for key in values if key not in primary]
            conflict = "DO UPDATE SET " + ", ".join(assignments) if assignments else "DO NOTHING"
            db.execute(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)}) ON CONFLICT({', '.join(primary)}) {conflict}", list(values.values()))


def restore_extensions(db, payload):
    records = []
    # Definitions precede their instances; campaign dependencies follow catalog order.
    from .import_writer import IMPORT_ORDER
    for entity in sorted(EXTENSIONS, key=IMPORT_ORDER.index):
        spec = EXTENSIONS[entity]
        rows = payload.get(spec["table"], [])
        if not isinstance(rows, list):
            raise ValidationError(f"`{spec['table']}` must be an array.")
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                raise ValidationError("Extension exports require object rows with IDs.")
            state = record_exists(db, entity, row["id"])
            if state == "deleted":
                raise ValidationError("Import cannot resurrect a deleted extension record.")
            records.append((save_extension(db, {**row, "entity_type": entity}, update=bool(state), restore=True), not state))
    return records


def restore_graph(db, payload):
    for row in payload.get("record_links", []):
        link_records(db, row, historical=True)
    for row in payload.get("import_identities", []):
        exists = db.execute("SELECT 1 FROM workflow_proposals WHERE id=?", (row["entity_id"],)).fetchone() if row["entity_type"] == "workflow_proposal" else record_exists(db, row["entity_type"], row["entity_id"])
        if not exists or exists == "deleted":
            raise ValidationError("Imported source identity references a missing record.")
        db.execute("INSERT INTO import_identities VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_id, source_key) DO UPDATE SET entity_type=excluded.entity_type, entity_id=excluded.entity_id, fingerprint=excluded.fingerprint",
                   [row[key] for key in ("source_id", "source_key", "entity_type", "entity_id", "fingerprint")])
