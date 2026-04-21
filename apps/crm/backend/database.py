"""Database schema and shared persistence helpers for CRM."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from errors import CrmValidationError
from models import ACTIVITY_TYPES, ENTITY_TYPES, RELATIONSHIP_KINDS, SCHEMA_VERSION


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def db_path(data_root: Path) -> Path:
    return data_root / "crm.sqlite"


def connect(data_root: Path) -> sqlite3.Connection:
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(data_root))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = MEMORY")
    connection.execute("PRAGMA synchronous = OFF")
    return connection


def ensure_schema(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    with connect(data_root) as db:
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
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS deals (
              id TEXT PRIMARY KEY,
              account_id TEXT NOT NULL DEFAULT '',
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
              owner_id TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT
            );
            CREATE TABLE IF NOT EXISTS relationships (
              id TEXT PRIMARY KEY,
              source_type TEXT NOT NULL,
              source_id TEXT NOT NULL,
              target_type TEXT NOT NULL,
              target_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              strength REAL NOT NULL DEFAULT 0.5,
              reason TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT
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
            CREATE INDEX IF NOT EXISTS idx_deals_account_stage ON deals(account_id, stage, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_deals_updated ON deals(updated_at);
            CREATE INDEX IF NOT EXISTS idx_activities_refs ON activities(account_id, contact_id, deal_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_type, source_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_type, target_id, deleted_at);
            """
        )
        db.execute(
            "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )


def normalize_entity_type(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in ENTITY_TYPES:
        raise CrmValidationError(f"Unsupported entity_type `{normalized}`.")
    return normalized


def normalize_relationship_kind(value: str) -> str:
    normalized = str(value or "related_to").strip()
    if normalized not in RELATIONSHIP_KINDS:
        raise CrmValidationError(f"Unsupported relationship kind `{normalized}`.")
    return normalized


def normalize_activity_type(value: str) -> str:
    normalized = str(value or "note").strip()
    if normalized not in ACTIVITY_TYPES:
        raise CrmValidationError(f"Unsupported activity_type `{normalized}`.")
    return normalized


def json_text(value: Any) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, sort_keys=True, ensure_ascii=False)


def row_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = dict(row)
    for key in ("metadata_json", "payload_json"):
        if key in payload:
            try:
                payload[key.removesuffix("_json")] = json.loads(payload.pop(key) or "{}")
            except json.JSONDecodeError:
                payload[key.removesuffix("_json")] = {}
    return payload


def record_event(
    db: sqlite3.Connection,
    *,
    event_type: str,
    entity_type: str = "",
    entity_id: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO events(id, event_type, entity_type, entity_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (new_id("event"), event_type, entity_type, entity_id, json_text(payload), now_timestamp()),
    )


def refresh_fts(db: sqlite3.Connection, *, entity_type: str, entity_id: str, title: str, body: str) -> None:
    db.execute("DELETE FROM crm_fts WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id))
    db.execute(
        "INSERT INTO crm_fts(entity_type, entity_id, title, body) VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, title, body),
    )


def entity_table(entity_type: str) -> str:
    return {
        "account": "accounts",
        "contact": "contacts",
        "deal": "deals",
        "activity": "activities",
    }[normalize_entity_type(entity_type)]


def health_payload(data_root: Path) -> dict[str, Any]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        schema_version = db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()["value"]
        counts = {}
        for entity_type, table in (("accounts", "accounts"), ("contacts", "contacts"), ("deals", "deals"), ("activities", "activities")):
            counts[entity_type] = db.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE deleted_at IS NULL").fetchone()["count"]
    return {"status": "ok", "schema_version": schema_version, **counts}
