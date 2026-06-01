"""SQLite storage for the CRM app."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from errors import NotFoundError, ValidationError

APP_VERSION = "0.4.2"
SCHEMA_VERSION = "6"
DB_NAME = "crm.sqlite"
CUSTOM_FIELD_TYPES = {"text", "number", "date", "boolean", "select", "multi_select", "url", "email"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@contextmanager
def connect(data_root: str | Path):
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / DB_NAME
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize(data_root: str | Path) -> None:
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    with connect(root) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              domain TEXT NOT NULL DEFAULT '',
              industry TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'prospect',
              owner_id TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS leads (
              id TEXT PRIMARY KEY,
              first_name TEXT NOT NULL DEFAULT '',
              last_name TEXT NOT NULL DEFAULT '',
              display_name TEXT NOT NULL,
              email TEXT NOT NULL DEFAULT '',
              phone TEXT NOT NULL DEFAULT '',
              company TEXT NOT NULL DEFAULT '',
              domain TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'new',
              owner_id TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              converted_at TEXT NOT NULL DEFAULT '',
              account_id TEXT NOT NULL DEFAULT '',
              contact_id TEXT NOT NULL DEFAULT '',
              deal_id TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS contacts (
              id TEXT PRIMARY KEY,
              account_id TEXT NOT NULL DEFAULT '',
              first_name TEXT NOT NULL DEFAULT '',
              last_name TEXT NOT NULL DEFAULT '',
              display_name TEXT NOT NULL,
              email TEXT NOT NULL DEFAULT '',
              phone TEXT NOT NULL DEFAULT '',
              role TEXT NOT NULL DEFAULT '',
              owner_id TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS pipelines (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              is_default INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pipeline_stages (
              id TEXT PRIMARY KEY,
              pipeline_id TEXT NOT NULL,
              name TEXT NOT NULL,
              position INTEGER NOT NULL,
              probability REAL NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deals (
              id TEXT PRIMARY KEY,
              account_id TEXT NOT NULL DEFAULT '',
              contact_id TEXT NOT NULL DEFAULT '',
              pipeline_id TEXT NOT NULL DEFAULT '',
              stage_id TEXT NOT NULL DEFAULT '',
              name TEXT NOT NULL,
              stage TEXT NOT NULL DEFAULT 'lead',
              value REAL NOT NULL DEFAULT 0,
              currency TEXT NOT NULL DEFAULT 'EUR',
              probability REAL NOT NULL DEFAULT 0,
              close_date TEXT NOT NULL DEFAULT '',
              owner_id TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS activities (
              id TEXT PRIMARY KEY,
              activity_type TEXT NOT NULL,
              subject TEXT NOT NULL,
              body TEXT NOT NULL DEFAULT '',
              account_id TEXT NOT NULL DEFAULT '',
              contact_id TEXT NOT NULL DEFAULT '',
              deal_id TEXT NOT NULL DEFAULT '',
              occurred_at TEXT NOT NULL,
              due_at TEXT NOT NULL DEFAULT '',
              completed_at TEXT NOT NULL DEFAULT '',
              owner_id TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'open',
              priority TEXT NOT NULL DEFAULT 'normal',
              due_at TEXT NOT NULL DEFAULT '',
              account_id TEXT NOT NULL DEFAULT '',
              contact_id TEXT NOT NULL DEFAULT '',
              deal_id TEXT NOT NULL DEFAULT '',
              owner_id TEXT NOT NULL DEFAULT '',
              body TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS notes (
              id TEXT PRIMARY KEY,
              body TEXT NOT NULL,
              account_id TEXT NOT NULL DEFAULT '',
              contact_id TEXT NOT NULL DEFAULT '',
              deal_id TEXT NOT NULL DEFAULT '',
              owner_id TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tags (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              color TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS record_tags (
              record_type TEXT NOT NULL,
              record_id TEXT NOT NULL,
              tag_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (record_type, record_id, tag_id)
            );
            CREATE TABLE IF NOT EXISTS saved_views (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              entity_type TEXT NOT NULL DEFAULT 'all',
              query TEXT NOT NULL DEFAULT '',
              filters_json TEXT NOT NULL DEFAULT '{}',
              refs_json TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS custom_field_definitions (
              id TEXT PRIMARY KEY,
              entity_type TEXT NOT NULL,
              field_key TEXT NOT NULL,
              label TEXT NOT NULL,
              field_type TEXT NOT NULL DEFAULT 'text',
              required INTEGER NOT NULL DEFAULT 0,
              options_json TEXT NOT NULL DEFAULT '[]',
              default_value_json TEXT NOT NULL DEFAULT 'null',
              position INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT,
              UNIQUE(entity_type, field_key)
            );
            CREATE TABLE IF NOT EXISTS custom_field_values (
              entity_type TEXT NOT NULL,
              entity_id TEXT NOT NULL,
              field_id TEXT NOT NULL,
              value_json TEXT NOT NULL DEFAULT 'null',
              updated_at TEXT NOT NULL,
              PRIMARY KEY(entity_type, entity_id, field_id)
            );
            CREATE TABLE IF NOT EXISTS automation_rules (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              trigger_event TEXT NOT NULL,
              entity_type TEXT NOT NULL DEFAULT 'all',
              conditions_json TEXT NOT NULL DEFAULT '{}',
              action_json TEXT NOT NULL DEFAULT '{}',
              approval_required INTEGER NOT NULL DEFAULT 1,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_proposals (
              id TEXT PRIMARY KEY,
              proposal_type TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              entity_type TEXT NOT NULL,
              entity_id TEXT NOT NULL,
              title TEXT NOT NULL,
              proposal_json TEXT NOT NULL DEFAULT '{}',
              source TEXT NOT NULL DEFAULT 'crm',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              approved_at TEXT NOT NULL DEFAULT '',
              applied_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS external_refs (
              id TEXT PRIMARY KEY,
              crm_entity_type TEXT NOT NULL,
              crm_entity_id TEXT NOT NULL,
              source_app_id TEXT NOT NULL,
              source_entity_type TEXT NOT NULL,
              source_entity_id TEXT NOT NULL,
              link_type TEXT NOT NULL DEFAULT 'related',
              provider_alias TEXT NOT NULL DEFAULT '',
              source_interface TEXT NOT NULL DEFAULT '',
              normalized_link_type TEXT NOT NULL DEFAULT 'related',
              title TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              occurred_at TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS website_intakes (
              id TEXT PRIMARY KEY,
              submission_id TEXT NOT NULL UNIQUE,
              lead_id TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'website',
              contact_email TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'accepted',
              email_status TEXT NOT NULL DEFAULT 'pending',
              payload_json TEXT NOT NULL DEFAULT '{}',
              server_meta_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS crm_outbox (
              id TEXT PRIMARY KEY,
              intake_id TEXT NOT NULL DEFAULT '',
              entity_type TEXT NOT NULL DEFAULT '',
              entity_id TEXT NOT NULL DEFAULT '',
              kind TEXT NOT NULL,
              provider_alias TEXT NOT NULL DEFAULT '',
              provider_app_id TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              attempts INTEGER NOT NULL DEFAULT 0,
              request_json TEXT NOT NULL DEFAULT '{}',
              result_json TEXT NOT NULL DEFAULT '{}',
              last_error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              processed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              entity_type TEXT NOT NULL DEFAULT '',
              entity_id TEXT NOT NULL DEFAULT '',
              payload_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS crm_fts USING fts5(
              entity_type UNINDEXED,
              entity_id UNINDEXED,
              title,
              body
            );
            CREATE INDEX IF NOT EXISTS idx_accounts_updated ON accounts(updated_at);
            CREATE INDEX IF NOT EXISTS idx_accounts_records_table ON accounts(owner_id, status, updated_at, deleted_at, archived_at);
            CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
            CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
            CREATE INDEX IF NOT EXISTS idx_leads_updated ON leads(updated_at);
            CREATE INDEX IF NOT EXISTS idx_leads_records_table ON leads(owner_id, status, source, updated_at, deleted_at, archived_at);
            CREATE INDEX IF NOT EXISTS idx_contacts_account ON contacts(account_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
            CREATE INDEX IF NOT EXISTS idx_contacts_records_table ON contacts(owner_id, updated_at, deleted_at, archived_at);
            CREATE INDEX IF NOT EXISTS idx_deals_account_stage ON deals(account_id, stage_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_deals_updated ON deals(updated_at);
            CREATE INDEX IF NOT EXISTS idx_deals_records_table ON deals(owner_id, stage_id, stage, close_date, value, updated_at, deleted_at, archived_at);
            CREATE INDEX IF NOT EXISTS idx_activities_refs ON activities(account_id, contact_id, deal_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, due_at, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_refs_status ON tasks(account_id, contact_id, deal_id, status, deleted_at, archived_at);
            CREATE INDEX IF NOT EXISTS idx_custom_field_definitions_entity ON custom_field_definitions(entity_type, archived_at, position);
            CREATE INDEX IF NOT EXISTS idx_custom_field_values_record ON custom_field_values(entity_type, entity_id);
            CREATE INDEX IF NOT EXISTS idx_custom_field_values_lookup ON custom_field_values(entity_type, field_id, value_json, entity_id);
            CREATE INDEX IF NOT EXISTS idx_record_tags_record ON record_tags(record_type, record_id, tag_id);
            CREATE INDEX IF NOT EXISTS idx_automation_rules_trigger ON automation_rules(trigger_event, entity_type, status);
            CREATE INDEX IF NOT EXISTS idx_workflow_proposals_record ON workflow_proposals(entity_type, entity_id, status);
            CREATE INDEX IF NOT EXISTS idx_external_refs_crm_record ON external_refs(crm_entity_type, crm_entity_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_external_refs_source ON external_refs(source_app_id, source_entity_type, source_entity_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_external_refs_occurred ON external_refs(occurred_at, updated_at);
            CREATE INDEX IF NOT EXISTS idx_website_intakes_submission ON website_intakes(submission_id);
            CREATE INDEX IF NOT EXISTS idx_website_intakes_lead ON website_intakes(lead_id);
            CREATE INDEX IF NOT EXISTS idx_crm_outbox_status ON crm_outbox(status, kind, updated_at);
            CREATE INDEX IF NOT EXISTS idx_crm_outbox_intake ON crm_outbox(intake_id, kind);
            """
        )
        _ensure_column(db, "leads", "converted_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "leads", "account_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "leads", "contact_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "leads", "deal_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "leads", "archived_at", "TEXT")
        _ensure_column(db, "accounts", "archived_at", "TEXT")
        _ensure_column(db, "contacts", "archived_at", "TEXT")
        _ensure_column(db, "deals", "contact_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "deals", "pipeline_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "deals", "stage_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "deals", "archived_at", "TEXT")
        _ensure_column(db, "activities", "due_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "activities", "completed_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "activities", "archived_at", "TEXT")
        _ensure_column(db, "tasks", "archived_at", "TEXT")
        _ensure_column(db, "notes", "archived_at", "TEXT")
        _ensure_column(db, "custom_field_definitions", "archived_at", "TEXT")
        _ensure_column(db, "external_refs", "provider_alias", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "external_refs", "source_interface", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "external_refs", "normalized_link_type", "TEXT NOT NULL DEFAULT 'related'")
        _ensure_column(db, "external_refs", "deleted_at", "TEXT")
        _ensure_column(db, "website_intakes", "server_meta_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(db, "crm_outbox", "provider_alias", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "crm_outbox", "provider_app_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "crm_outbox", "processed_at", "TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_external_refs_provider ON external_refs(provider_alias, source_interface, normalized_link_type, deleted_at)")
        _seed_pipeline(db)
        db.execute("INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)", ("schema_version", SCHEMA_VERSION))
        db.execute("INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)", ("app_version", APP_VERSION))
    marker = {"app_id": "crm", "app_version": APP_VERSION, "data_schema_version": SCHEMA_VERSION, "updated_at": utc_now()}
    (root / ".maverick-app.json").write_text(json.dumps(marker, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    view_state_path = root / "view_state.json"
    if not view_state_path.exists():
        view_state_path.write_text(
            json.dumps(
                {"schema_version": "1", "view_filter": {"entity_type": "all", "mode": "search", "query": "", "refs": [], "title": "", "updated_at": ""}},
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _seed_pipeline(db: sqlite3.Connection) -> None:
    now = utc_now()
    pipeline = db.execute("SELECT id FROM pipelines WHERE is_default = 1 LIMIT 1").fetchone()
    pipeline_id = str(pipeline["id"]) if pipeline else "pipeline_default"
    db.execute(
        "INSERT OR IGNORE INTO pipelines(id, name, is_default, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
        (pipeline_id, "Sales pipeline", now, now),
    )
    stages = [("lead", "Lead", 10, 0.1), ("qualified", "Qualified", 20, 0.3), ("proposal", "Proposal", 30, 0.6), ("won", "Won", 40, 1.0), ("lost", "Lost", 50, 0.0)]
    for stage_id, name, position, probability in stages:
        db.execute(
            """
            INSERT OR IGNORE INTO pipeline_stages(id, pipeline_id, name, position, probability, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (stage_id, pipeline_id, name, position, probability, now, now),
        )


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for key in list(item.keys()):
        if key.endswith("_json"):
            raw_value = item.pop(key)
            item[key[:-5]] = json.loads(raw_value or "null")
    return item


def tags_for_record(db: sqlite3.Connection, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT tags.id, tags.name, tags.color, record_tags.created_at
        FROM record_tags
        JOIN tags ON tags.id = record_tags.tag_id
        WHERE record_tags.record_type = ? AND record_tags.record_id = ?
        ORDER BY lower(tags.name)
        """,
        (entity_type, entity_id),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def attach_tags(db: sqlite3.Connection, entity_type: str, record: dict[str, Any]) -> dict[str, Any]:
    record["tags"] = tags_for_record(db, entity_type, str(record.get("id") or ""))
    record["custom_fields"] = custom_fields_for_record(db, entity_type, str(record.get("id") or ""))
    return record


def custom_fields_for_record(db: sqlite3.Connection, entity_type: str, entity_id: str) -> dict[str, Any]:
    if not entity_id:
        return {}
    rows = db.execute(
        """
        SELECT custom_field_definitions.field_key, custom_field_values.value_json
        FROM custom_field_definitions
        LEFT JOIN custom_field_values
          ON custom_field_values.field_id = custom_field_definitions.id
         AND custom_field_values.entity_type = custom_field_definitions.entity_type
         AND custom_field_values.entity_id = ?
        WHERE custom_field_definitions.entity_type = ?
          AND custom_field_definitions.archived_at IS NULL
        ORDER BY custom_field_definitions.position, lower(custom_field_definitions.label)
        """,
        (entity_id, entity_type),
    ).fetchall()
    values: dict[str, Any] = {}
    for row in rows:
        values[str(row["field_key"])] = json.loads(row["value_json"] or "null") if row["value_json"] is not None else None
    return values


def write_event(db: sqlite3.Connection, event_type: str, entity_type: str = "", entity_id: str = "", payload: dict[str, Any] | None = None) -> None:
    db.execute(
        "INSERT INTO events(id, event_type, entity_type, entity_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_id("evt"), event_type, entity_type, entity_id, json.dumps(payload or {}, ensure_ascii=True), utc_now()),
    )


def upsert_fts(db: sqlite3.Connection, entity_type: str, entity_id: str, title: str, body: str) -> None:
    db.execute("DELETE FROM crm_fts WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id))
    db.execute("INSERT INTO crm_fts(entity_type, entity_id, title, body) VALUES (?, ?, ?, ?)", (entity_type, entity_id, title, body))


def delete_fts(db: sqlite3.Connection, entity_type: str, entity_id: str) -> None:
    db.execute("DELETE FROM crm_fts WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id))


def require_text(payload: dict[str, Any], key: str, *, default: str = "", required: bool = False) -> str:
    value = payload.get(key, default)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"`{key}` must be a string.")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"`{key}` is required.")
    return value


def metadata(payload: dict[str, Any]) -> str:
    value = payload.get("metadata") or {}
    if not isinstance(value, dict):
        raise ValidationError("`metadata` must be an object.")
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def list_rows(db: sqlite3.Connection, table: str, *, limit: int = 50, query: str = "", max_limit: int | None = 200, include_archived: bool = False) -> list[dict[str, Any]]:
    limit = max(1, min(limit, max_limit)) if max_limit is not None else max(1, limit)
    visibility = "deleted_at IS NULL" if include_archived else "deleted_at IS NULL AND archived_at IS NULL"
    if query:
        pattern = f"%{query.lower()}%"
        if table == "accounts":
            rows = db.execute(
                f"SELECT * FROM accounts WHERE {visibility} AND lower(name || ' ' || domain || ' ' || summary) LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        elif table == "leads":
            rows = db.execute(
                f"SELECT * FROM leads WHERE {visibility} AND lower(display_name || ' ' || email || ' ' || company || ' ' || domain || ' ' || summary) LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        elif table == "contacts":
            rows = db.execute(
                f"SELECT * FROM contacts WHERE {visibility} AND lower(display_name || ' ' || email || ' ' || summary) LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        elif table == "deals":
            rows = db.execute(
                f"SELECT * FROM deals WHERE {visibility} AND lower(name || ' ' || summary) LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        else:
            rows = db.execute(f"SELECT * FROM {table} WHERE {visibility} ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = db.execute(f"SELECT * FROM {table} WHERE {visibility} ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    entity_type = entity_type_for_table(table)
    return [attach_tags(db, entity_type, row_to_dict(row)) for row in rows]


def get_record(db: sqlite3.Connection, entity_type: str, entity_id: str) -> dict[str, Any]:
    table = table_for_entity(entity_type)
    row = db.execute(f"SELECT * FROM {table} WHERE id = ? AND deleted_at IS NULL AND archived_at IS NULL", (entity_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"{entity_type} `{entity_id}` was not found.")
    record = row_to_dict(row)
    record["entity_type"] = entity_type
    return attach_tags(db, entity_type, record)


def table_for_entity(entity_type: str) -> str:
    mapping = {"lead": "leads", "account": "accounts", "contact": "contacts", "deal": "deals", "activity": "activities", "task": "tasks", "note": "notes"}
    try:
        return mapping[entity_type]
    except KeyError as error:
        raise ValidationError("Unsupported entity_type.", details={"entity_type": entity_type}) from error


def entity_type_for_table(table: str) -> str:
    mapping = {"leads": "lead", "accounts": "account", "contacts": "contact", "deals": "deal", "activities": "activity", "tasks": "task", "notes": "note"}
    try:
        return mapping[table]
    except KeyError as error:
        raise ValidationError("Unsupported CRM table.", details={"table": table}) from error


def parse_limit(payload: dict[str, Any], default: int = 50) -> int:
    value = payload.get("limit", default)
    if not isinstance(value, int):
        raise ValidationError("`limit` must be an integer.")
    return max(1, min(value, 200))


def export_payload(db: sqlite3.Connection) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": utc_now(),
        "custom_field_definitions": [row_to_dict(row) for row in db.execute("SELECT * FROM custom_field_definitions ORDER BY entity_type, position, label").fetchall()],
        "custom_field_values": [row_to_dict(row) for row in db.execute("SELECT * FROM custom_field_values ORDER BY entity_type, entity_id, field_id").fetchall()],
        "automation_rules": [row_to_dict(row) for row in db.execute("SELECT * FROM automation_rules ORDER BY updated_at DESC").fetchall()],
        "workflow_proposals": [row_to_dict(row) for row in db.execute("SELECT * FROM workflow_proposals ORDER BY updated_at DESC").fetchall()],
        "external_refs": [row_to_dict(row) for row in db.execute("SELECT * FROM external_refs WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall()],
        "leads": list_rows(db, "leads", limit=1_000_000, max_limit=None, include_archived=True),
        "accounts": list_rows(db, "accounts", limit=1_000_000, max_limit=None, include_archived=True),
        "contacts": list_rows(db, "contacts", limit=1_000_000, max_limit=None, include_archived=True),
        "deals": list_rows(db, "deals", limit=1_000_000, max_limit=None, include_archived=True),
        "activities": list_rows(db, "activities", limit=1_000_000, max_limit=None, include_archived=True),
        "tasks": list_rows(db, "tasks", limit=1_000_000, max_limit=None, include_archived=True),
        "notes": list_rows(db, "notes", limit=1_000_000, max_limit=None, include_archived=True),
    }


def count_tables(db: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    return {table: int(db.execute(f"SELECT count(*) FROM {table} WHERE deleted_at IS NULL AND archived_at IS NULL").fetchone()[0]) for table in tables}
