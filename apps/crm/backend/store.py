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

APP_VERSION = "0.1.0"
SCHEMA_VERSION = "1"
DB_NAME = "crm.sqlite"


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
            CREATE INDEX IF NOT EXISTS idx_contacts_account ON contacts(account_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
            CREATE INDEX IF NOT EXISTS idx_deals_account_stage ON deals(account_id, stage_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_deals_updated ON deals(updated_at);
            CREATE INDEX IF NOT EXISTS idx_activities_refs ON activities(account_id, contact_id, deal_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, due_at, deleted_at);
            """
        )
        _ensure_column(db, "accounts", "archived_at", "TEXT")
        _ensure_column(db, "contacts", "archived_at", "TEXT")
        _ensure_column(db, "deals", "contact_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "deals", "pipeline_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "deals", "stage_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "deals", "archived_at", "TEXT")
        _ensure_column(db, "activities", "due_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "activities", "completed_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "activities", "archived_at", "TEXT")
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
    for key in ("metadata_json", "payload_json"):
        if key in item:
            item[key.replace("_json", "")] = json.loads(item.pop(key) or "{}")
    return item


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


def list_rows(db: sqlite3.Connection, table: str, *, limit: int = 50, query: str = "") -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    if query:
        pattern = f"%{query.lower()}%"
        if table == "accounts":
            rows = db.execute(
                "SELECT * FROM accounts WHERE deleted_at IS NULL AND lower(name || ' ' || domain || ' ' || summary) LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        elif table == "contacts":
            rows = db.execute(
                "SELECT * FROM contacts WHERE deleted_at IS NULL AND lower(display_name || ' ' || email || ' ' || summary) LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        elif table == "deals":
            rows = db.execute(
                "SELECT * FROM deals WHERE deleted_at IS NULL AND lower(name || ' ' || summary) LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        else:
            rows = db.execute(f"SELECT * FROM {table} WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = db.execute(f"SELECT * FROM {table} WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(row) for row in rows]


def get_record(db: sqlite3.Connection, entity_type: str, entity_id: str) -> dict[str, Any]:
    table = table_for_entity(entity_type)
    row = db.execute(f"SELECT * FROM {table} WHERE id = ? AND deleted_at IS NULL", (entity_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"{entity_type} `{entity_id}` was not found.")
    record = row_to_dict(row)
    record["entity_type"] = entity_type
    return record


def table_for_entity(entity_type: str) -> str:
    mapping = {"account": "accounts", "contact": "contacts", "deal": "deals", "activity": "activities", "task": "tasks", "note": "notes"}
    try:
        return mapping[entity_type]
    except KeyError as error:
        raise ValidationError("Unsupported entity_type.", details={"entity_type": entity_type}) from error


def parse_limit(payload: dict[str, Any], default: int = 50) -> int:
    value = payload.get("limit", default)
    if not isinstance(value, int):
        raise ValidationError("`limit` must be an integer.")
    return max(1, min(value, 200))


def export_payload(db: sqlite3.Connection) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": utc_now(),
        "accounts": list_rows(db, "accounts", limit=1000),
        "contacts": list_rows(db, "contacts", limit=1000),
        "deals": list_rows(db, "deals", limit=1000),
        "activities": list_rows(db, "activities", limit=1000),
        "tasks": list_rows(db, "tasks", limit=1000),
        "notes": list_rows(db, "notes", limit=1000),
    }


def count_tables(db: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    return {table: int(db.execute(f"SELECT count(*) FROM {table} WHERE deleted_at IS NULL").fetchone()[0]) for table in tables}
