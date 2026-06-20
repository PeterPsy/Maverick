"""SQLite database helpers for the Senses app."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3


SCHEMA_VERSION = "1"
DB_FILENAME = "senses.sqlite"
WORKSPACE_TABLES = ("schema_migrations", "settings")


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def db_path(data_root: Path) -> Path:
    return data_root / DB_FILENAME


def connect(data_root: Path) -> sqlite3.Connection:
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(data_root))
    connection.row_factory = sqlite3.Row
    return connection


def ensure_schema(data_root: Path, workspace_id: str) -> None:
    workspace = _workspace_id(workspace_id)
    timestamp = now_timestamp()
    db = connect(data_root)
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
              workspace_id TEXT NOT NULL,
              version TEXT NOT NULL,
              applied_at TEXT NOT NULL,
              PRIMARY KEY (workspace_id, version)
            );

            CREATE TABLE IF NOT EXISTS settings (
              workspace_id TEXT PRIMARY KEY,
              auth_mode TEXT NOT NULL DEFAULT 'user_session_mvp',
              device_ingress_enabled INTEGER NOT NULL DEFAULT 0,
              max_frame_bytes INTEGER NOT NULL DEFAULT 8388608,
              max_audio_bytes INTEGER NOT NULL DEFAULT 10485760,
              jpeg_quality_hint REAL NOT NULL DEFAULT 0.78,
              routing_followup_window_seconds INTEGER NOT NULL DEFAULT 300,
              default_retention_class TEXT NOT NULL DEFAULT 'chat_attachment',
              failed_capture_ttl_seconds INTEGER NOT NULL DEFAULT 86400,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
        """)
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(workspace_id, version, applied_at) VALUES (?, ?, ?)",
            (workspace, SCHEMA_VERSION, timestamp),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO settings(
              workspace_id,
              created_at,
              updated_at
            ) VALUES (?, ?, ?)
            """,
            (workspace, timestamp, timestamp),
        )
        db.commit()
    finally:
        db.close()


def settings_payload(data_root: Path, workspace_id: str) -> dict[str, object]:
    workspace = _workspace_id(workspace_id)
    ensure_schema(data_root, workspace)
    db = connect(data_root)
    try:
        row = db.execute("SELECT * FROM settings WHERE workspace_id = ?", (workspace,)).fetchone()
    finally:
        db.close()
    if row is None:
        raise RuntimeError(f"Senses settings were not initialized for workspace `{workspace}`.")
    payload = dict(row)
    payload["device_ingress_enabled"] = bool(payload["device_ingress_enabled"])
    return payload


def health_payload(data_root: Path, workspace_id: str) -> dict[str, object]:
    workspace = _workspace_id(workspace_id)
    ensure_schema(data_root, workspace)
    db = connect(data_root)
    try:
        migrations = [
            dict(row)
            for row in db.execute(
                "SELECT version, applied_at FROM schema_migrations WHERE workspace_id = ? ORDER BY version",
                (workspace,),
            ).fetchall()
        ]
    finally:
        db.close()
    return {
        "database": {
            "path": str(db_path(data_root)),
            "schema_version": SCHEMA_VERSION,
            "migrations": migrations,
            "tables": list(WORKSPACE_TABLES),
        },
        "settings": settings_payload(data_root, workspace),
    }


def table_columns(data_root: Path, table_name: str) -> list[str]:
    db = connect(data_root)
    try:
        return [str(row["name"]) for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()]
    finally:
        db.close()


def _workspace_id(value: str | None) -> str:
    workspace = str(value or "").strip()
    return workspace or "default"
