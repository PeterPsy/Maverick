"""SQLite database helpers for the Senses app."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3


SCHEMA_VERSION = "3"
DB_FILENAME = "senses.sqlite"
PRIMARY_DB_PATH = f"data/senses/{DB_FILENAME}"
WORKSPACE_TABLES = (
    "schema_migrations",
    "settings",
    "devices",
    "pairing_sessions",
    "device_sessions",
    "ingestion_requests",
    "captures",
    "audit",
)


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def db_path(data_root: Path) -> Path:
    return data_root / DB_FILENAME


def connect(data_root: Path) -> sqlite3.Connection:
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(data_root))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
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
              allow_member_pairing INTEGER NOT NULL DEFAULT 1,
              require_admin_for_settings INTEGER NOT NULL DEFAULT 1,
              pairing_code_ttl_seconds INTEGER NOT NULL DEFAULT 600,
              max_frame_bytes INTEGER NOT NULL DEFAULT 8388608,
              max_audio_bytes INTEGER NOT NULL DEFAULT 10485760,
              jpeg_quality_hint REAL NOT NULL DEFAULT 0.78,
              routing_followup_window_seconds INTEGER NOT NULL DEFAULT 300,
              default_retention_class TEXT NOT NULL DEFAULT 'chat_attachment',
              failed_capture_ttl_seconds INTEGER NOT NULL DEFAULT 86400,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pairing_sessions (
              workspace_id TEXT NOT NULL,
              pairing_id TEXT NOT NULL,
              code_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              created_by_user_id TEXT NOT NULL,
              completed_by_user_id TEXT,
              device_id TEXT,
              device_display_name TEXT,
              device_kind TEXT,
              platform TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              completed_at TEXT,
              revoked_at TEXT,
              revoked_by_user_id TEXT,
              PRIMARY KEY (workspace_id, pairing_id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_senses_pairing_code
              ON pairing_sessions(workspace_id, code_hash)
              WHERE status = 'pending';

            CREATE INDEX IF NOT EXISTS idx_senses_pairing_status
              ON pairing_sessions(workspace_id, status, expires_at);

            CREATE TABLE IF NOT EXISTS devices (
              workspace_id TEXT NOT NULL,
              device_id TEXT NOT NULL,
              owner_user_id TEXT NOT NULL,
              display_name TEXT NOT NULL,
              device_kind TEXT NOT NULL,
              platform TEXT NOT NULL,
              status TEXT NOT NULL,
              pairing_id TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              paired_at TEXT NOT NULL,
              last_seen_at TEXT,
              revoked_at TEXT,
              revoked_by_user_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (workspace_id, device_id)
            );

            CREATE INDEX IF NOT EXISTS idx_senses_devices_owner_status
              ON devices(workspace_id, owner_user_id, status, updated_at);

            CREATE TABLE IF NOT EXISTS device_sessions (
              workspace_id TEXT NOT NULL,
              device_session_id TEXT NOT NULL,
              device_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              auth_mode TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              last_seen_at TEXT,
              revoked_at TEXT,
              revoked_by_user_id TEXT,
              PRIMARY KEY (workspace_id, device_session_id),
              FOREIGN KEY (workspace_id, device_id)
                REFERENCES devices(workspace_id, device_id)
                ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_senses_device_sessions_device
              ON device_sessions(workspace_id, device_id, status);

            CREATE TABLE IF NOT EXISTS ingestion_requests (
              workspace_id TEXT NOT NULL,
              request_id TEXT NOT NULL,
              device_id TEXT NOT NULL,
              device_session_id TEXT,
              idempotency_key TEXT NOT NULL,
              client_capture_id TEXT,
              capture_id TEXT,
              request_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              error_code TEXT,
              created_at TEXT NOT NULL,
              completed_at TEXT,
              PRIMARY KEY (workspace_id, request_id),
              UNIQUE (workspace_id, device_id, idempotency_key)
            );

            CREATE INDEX IF NOT EXISTS idx_senses_ingestion_status_time
              ON ingestion_requests(workspace_id, status, created_at DESC);

            CREATE TABLE IF NOT EXISTS captures (
              workspace_id TEXT NOT NULL,
              capture_id TEXT NOT NULL,
              device_id TEXT NOT NULL,
              device_session_id TEXT,
              ingestion_request_id TEXT,
              input_mode TEXT NOT NULL,
              prompt TEXT NOT NULL,
              content_type TEXT NOT NULL,
              storage_file_id TEXT,
              workspace_relative_path TEXT,
              sha256 TEXT,
              size_bytes INTEGER NOT NULL,
              width INTEGER,
              height INTEGER,
              retention_class TEXT NOT NULL,
              status TEXT NOT NULL,
              error_code TEXT,
              captured_at TEXT NOT NULL,
              ingested_at TEXT,
              runtime_session_id TEXT,
              thread_id TEXT,
              turn_id TEXT,
              deleted_at TEXT,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (workspace_id, capture_id),
              FOREIGN KEY (workspace_id, device_id)
                REFERENCES devices(workspace_id, device_id)
                ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_senses_captures_device_time
              ON captures(workspace_id, device_id, captured_at DESC);

            CREATE INDEX IF NOT EXISTS idx_senses_captures_status_time
              ON captures(workspace_id, status, captured_at DESC);

            CREATE INDEX IF NOT EXISTS idx_senses_captures_runtime
              ON captures(workspace_id, runtime_session_id, turn_id);

            CREATE TABLE IF NOT EXISTS audit (
              workspace_id TEXT NOT NULL,
              audit_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              actor_user_id TEXT,
              device_id TEXT,
              pairing_id TEXT,
              details_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              PRIMARY KEY (workspace_id, audit_id)
            );

            CREATE INDEX IF NOT EXISTS idx_senses_audit_created
              ON audit(workspace_id, created_at);
        """)
        _ensure_settings_columns(db)
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
    payload["allow_member_pairing"] = bool(payload["allow_member_pairing"])
    payload["require_admin_for_settings"] = bool(payload["require_admin_for_settings"])
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
        counts = {
            table: int(
                db.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id = ?", (workspace,)).fetchone()[0]
            )
            for table in WORKSPACE_TABLES
            if table != "schema_migrations"
        }
    finally:
        db.close()
    return {
        "database": {
            "primary_path": PRIMARY_DB_PATH,
            "schema_version": SCHEMA_VERSION,
            "migrations": migrations,
            "tables": list(WORKSPACE_TABLES),
            "counts": counts,
        },
        "settings": settings_payload(data_root, workspace),
    }


def table_columns(data_root: Path, table_name: str) -> list[str]:
    db = connect(data_root)
    try:
        return [str(row["name"]) for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()]
    finally:
        db.close()


def decode_json_object(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def encode_json_object(value: object) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=True, sort_keys=True)


def require_workspace_id(value: str | None) -> str:
    workspace = str(value or "").strip()
    if not workspace:
        raise ValueError("Senses entrypoint payload requires workspace_id.")
    return workspace


def _workspace_id(value: str | None) -> str:
    return require_workspace_id(value)


def _ensure_settings_columns(db: sqlite3.Connection) -> None:
    columns = set(_table_column_names(db, "settings"))
    additions = {
        "allow_member_pairing": "allow_member_pairing INTEGER NOT NULL DEFAULT 1",
        "require_admin_for_settings": "require_admin_for_settings INTEGER NOT NULL DEFAULT 1",
        "pairing_code_ttl_seconds": "pairing_code_ttl_seconds INTEGER NOT NULL DEFAULT 600",
    }
    for name, definition in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE settings ADD COLUMN {definition}")


def _table_column_names(db: sqlite3.Connection, table_name: str) -> list[str]:
    return [str(row["name"]) for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()]
