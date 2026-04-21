"""Database setup and connection helpers for Gmail App."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterator

from errors import GmailAppValidationError
from gmail_models import utc_now

SCHEMA_VERSION = "1"
DB_NAME = "gmail.sqlite"
STATE_NAME = "state.json"


def validate_data_root(data_root: Path) -> Path:
    root = data_root.resolve()
    if root.name != "gmail-app":
        raise GmailAppValidationError("Gmail App data root must end with data/gmail-app.")
    return root


def db_path(data_root: Path) -> Path:
    return validate_data_root(data_root) / DB_NAME


def state_path(data_root: Path) -> Path:
    return validate_data_root(data_root) / STATE_NAME


@contextmanager
def connect(data_root: Path) -> Iterator[sqlite3.Connection]:
    ensure_schema(data_root)
    connection = sqlite3.connect(db_path(data_root))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def ensure_schema(data_root: Path) -> None:
    root = validate_data_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    state = state_path(root)
    if not state.exists():
        state.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "created_at": utc_now(),
                    "oauth_secret_ref": "",
                    "retention_mode": "reviewed_threads",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    connection = sqlite3.connect(db_path(root))
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS gmail_accounts (
              email TEXT PRIMARY KEY,
              display_name TEXT NOT NULL DEFAULT '',
              oauth_secret_ref TEXT NOT NULL DEFAULT '',
              connected_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS threads (
              id TEXT PRIMARY KEY,
              subject TEXT NOT NULL,
              participants_json TEXT NOT NULL,
              snippet TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              is_unread INTEGER NOT NULL DEFAULT 0,
              labels_json TEXT NOT NULL DEFAULT '[]',
              last_reviewed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              from_email TEXT NOT NULL,
              to_emails_json TEXT NOT NULL,
              subject TEXT NOT NULL,
              snippet TEXT NOT NULL,
              body_text TEXT NOT NULL,
              received_at TEXT NOT NULL,
              is_unread INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY(thread_id) REFERENCES threads(id)
            );
            CREATE TABLE IF NOT EXISTS relationship_suggestions (
              id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              title TEXT NOT NULL,
              email TEXT NOT NULL DEFAULT '',
              domain TEXT NOT NULL DEFAULT '',
              note TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL,
              decided_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS suggestion_decisions (
              id TEXT PRIMARY KEY,
              suggestion_id TEXT NOT NULL,
              decision TEXT NOT NULL,
              result_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS send_approvals (
              id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              to_emails_json TEXT NOT NULL,
              subject TEXT NOT NULL,
              body_text TEXT NOT NULL,
              thread_id TEXT NOT NULL DEFAULT '',
              confirmation_text TEXT NOT NULL,
              created_at TEXT NOT NULL,
              approved_at TEXT NOT NULL DEFAULT '',
              consumed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS sent_messages (
              id TEXT PRIMARY KEY,
              approval_id TEXT NOT NULL,
              gmail_message_id TEXT NOT NULL,
              thread_id TEXT NOT NULL DEFAULT '',
              sent_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
              id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              actor TEXT NOT NULL,
              subject_id TEXT NOT NULL DEFAULT '',
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        connection.execute("INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)", ("schema_version", SCHEMA_VERSION))
        ensure_column(connection, "threads", "is_unread", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "threads", "labels_json", "TEXT NOT NULL DEFAULT '[]'")
        ensure_column(connection, "messages", "is_unread", "INTEGER NOT NULL DEFAULT 0")
        connection.commit()
    finally:
        connection.close()


def health_payload(data_root: Path) -> dict[str, Any]:
    ensure_schema(data_root)
    with sqlite3.connect(db_path(data_root)) as connection:
        schema_version = connection.execute("SELECT value FROM schema_metadata WHERE key = ?", ("schema_version",)).fetchone()[0]
        account_count = connection.execute("SELECT COUNT(*) FROM gmail_accounts").fetchone()[0]
    return {
        "status": "healthy",
        "schema_version": schema_version,
        "database": str(db_path(data_root)),
        "state_file": str(state_path(data_root)),
        "connected_accounts": account_count,
    }


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str) -> Any:
    return json.loads(value or "null")


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
