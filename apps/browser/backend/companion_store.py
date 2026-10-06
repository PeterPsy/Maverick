"""Workspace-owned durable Chrome connection and operation store."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
 session_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
 display_name TEXT NOT NULL, secret_hash TEXT NOT NULL, status TEXT NOT NULL,
 created_at REAL NOT NULL, seen_at REAL NOT NULL, expires_at REAL NOT NULL,
 tab_url TEXT NOT NULL DEFAULT '', tab_title TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS operations (
 operation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, action TEXT NOT NULL,
 input_json TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
 expires_at REAL NOT NULL, lease_id TEXT, lease_until REAL,
 result_json TEXT, progress_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS operation_session_status ON operations(session_id, status, created_at);
CREATE TABLE IF NOT EXISTS media_requests (
 request_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, item_key TEXT NOT NULL,
 dependency_alias TEXT NOT NULL, expected_path TEXT, status TEXT NOT NULL
);
"""


@contextmanager
def database(data_root: Path) -> Iterator[sqlite3.Connection]:
    data_root.mkdir(parents=True, exist_ok=True)
    path = data_root / "companion.sqlite3"
    if path.is_symlink():
        raise ValueError("Browser connection database must not be a symlink.")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    os.chmod(path, 0o600)
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SCHEMA)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def sweep(connection: sqlite3.Connection, now: float) -> None:
    connection.execute(
        "UPDATE connections SET status='offline' WHERE status IN ('connecting','connected') AND expires_at <= ?", (now,)
    )
    connection.execute(
        "UPDATE operations SET status='expired', result_json=? WHERE status IN ('queued','running','processing_media') "
        "AND (expires_at <= ? OR (status='running' AND lease_until <= ?))",
        (encoded({"error": "operation_expired", "detail": "The Chrome connector did not complete its lease."}), now, now),
    )
    connection.execute("DELETE FROM operations WHERE expires_at < ?", (now - 3600,))
    # Bounded retained observations; pending work is never evicted for old results.
    rows = connection.execute("SELECT operation_id,length(result_json) AS size FROM operations WHERE status IN ('completed','failed','cancelled','expired') ORDER BY created_at DESC").fetchall()
    total = 0
    for index, row in enumerate(rows):
        total += row["size"] or 0
        if index >= 256 or total > 64 * 1024 * 1024:
            connection.execute("DELETE FROM operations WHERE operation_id=?", (row["operation_id"],))
    connection.execute("DELETE FROM media_requests WHERE operation_id NOT IN (SELECT operation_id FROM operations)")
    connection.execute("DELETE FROM connections WHERE seen_at < ?", (now - 86400,))


def public_connection(row: sqlite3.Row) -> dict:
    return {
        "session_id": row["session_id"], "provider": "chrome_companion", "status": row["status"],
        "display_name": row["display_name"], "url": row["tab_url"], "title": row["tab_title"],
        "last_seen": row["seen_at"], "expires_at": row["expires_at"], "owned_by": "user",
    }


def public_operation(row: sqlite3.Row, *, include_result: bool = True) -> dict:
    result = {
        "operation_id": row["operation_id"], "session_id": row["session_id"], "action": row["action"],
        "status": row["status"], "created_at": row["created_at"], "expires_at": row["expires_at"],
        "progress": json.loads(row["progress_json"]), "data_class": "personal",
    }
    if include_result and row["result_json"]:
        result["result"] = json.loads(row["result_json"])
    return result
