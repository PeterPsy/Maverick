"""Additive schema and export support for native CRM extensions."""

import json

from entity_catalog import ENTITY_TABLES, EXTENSIONS


def initialize_extensions(db):
    for spec in EXTENSIONS.values():
        columns = []
        for field, kind in spec["fields"].items():
            if kind == "integer":
                columns.append(f"{field} INTEGER NOT NULL DEFAULT 0")
            elif kind == "json":
                columns.append(f"{field}_json TEXT NOT NULL DEFAULT '{{}}'")
            else:
                columns.append(f"{field} TEXT NOT NULL DEFAULT ''")
        table = spec["table"]
        db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
            owner_id TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT, deleted_at TEXT,
            {', '.join(columns)}
        )""")
        db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_updated ON {table}(deleted_at, archived_at, updated_at, id)")
        for field, kind in spec["fields"].items():
            if kind.startswith("ref:"):
                db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{field} ON {table}({field}, deleted_at)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_object_key ON custom_object_definitions(object_key)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_position ON campaign_steps(campaign_id, position) WHERE deleted_at IS NULL")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_recipient ON campaign_members(campaign_id, record_type, record_id) WHERE deleted_at IS NULL")
    db.execute("""CREATE TABLE IF NOT EXISTS record_links (
        id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
        target_type TEXT NOT NULL, target_id TEXT NOT NULL, relationship TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE(source_type, source_id, target_type, target_id, relationship)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_record_links_target ON record_links(target_type, target_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS import_jobs (
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
        plan_token TEXT NOT NULL UNIQUE, report_json TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS import_rows (
        job_id TEXT NOT NULL REFERENCES import_jobs(id), row_number INTEGER NOT NULL,
        entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, outcome TEXT NOT NULL,
        PRIMARY KEY(job_id, row_number)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS import_identities (
        source_id TEXT NOT NULL, source_key TEXT NOT NULL, entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
        PRIMARY KEY(source_id, source_key)
    )""")


def export_extensions(db):
    result = {}
    for table in [*(spec["table"] for spec in EXTENSIONS.values()), "record_links", "import_identities"]:
        visibility = " WHERE deleted_at IS NULL" if table not in {"record_links", "import_identities"} else ""
        rows = []
        for row in db.execute(f"SELECT * FROM {table}{visibility} ORDER BY 1"):
            item = dict(row)
            if table == "import_identities":
                target = ENTITY_TABLES.get(item["entity_type"])
                if target and not db.execute(f"SELECT 1 FROM {target} WHERE id=? AND deleted_at IS NULL", (item["entity_id"],)).fetchone():
                    # Native exports intentionally omit tombstones. Do not emit
                    # identities whose target cannot exist in the same export.
                    continue
            for key in list(item):
                if key.endswith("_json"):
                    item[key[:-5]] = json.loads(item.pop(key))
            rows.append(item)
        result[table] = rows
    return result
