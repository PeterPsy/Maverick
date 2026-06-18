"""SQLite database helpers for the Mail app."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from collections.abc import Iterator
import json
from pathlib import Path
import re
import sqlite3


SCHEMA_VERSION = "8"
REFERENCE_ENTITIES = ["mail_connection", "email_thread", "email_message", "mail_attachment", "mail_draft"]
REQUIRED_TABLES = [
    "schema_metadata",
    "connections",
    "oauth_credentials",
    "provider_credentials",
    "oauth_flows",
    "folders",
    "labels",
    "threads",
    "messages",
    "attachments",
    "drafts",
    "sync_state",
    "entity_links",
    "audit_log",
]


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def db_path(data_root: Path) -> Path:
    return data_root / "mail.sqlite"


@contextmanager
def connect(data_root: Path) -> Iterator[sqlite3.Connection]:
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(data_root))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_schema(data_root: Path) -> None:
    with connect(data_root) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connections (
              id TEXT PRIMARY KEY,
              provider TEXT NOT NULL,
              email_address TEXT NOT NULL,
              display_name TEXT NOT NULL,
              status TEXT NOT NULL,
              scopes_json TEXT NOT NULL DEFAULT '[]',
              settings_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_credentials (
              id TEXT PRIMARY KEY,
              connection_id TEXT NOT NULL,
              provider TEXT NOT NULL,
              secret_ref TEXT NOT NULL DEFAULT '',
              encrypted_token_json TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_credentials (
              id TEXT PRIMARY KEY,
              connection_id TEXT NOT NULL,
              provider TEXT NOT NULL,
              logical_name TEXT NOT NULL,
              secret_ref TEXT NOT NULL DEFAULT '',
              grant_id TEXT NOT NULL DEFAULT '',
              resource_type TEXT NOT NULL DEFAULT '',
              resource_id TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(connection_id, logical_name)
            );
            CREATE TABLE IF NOT EXISTS oauth_flows (
              state TEXT PRIMARY KEY,
              provider TEXT NOT NULL,
              status TEXT NOT NULL,
              scopes_json TEXT NOT NULL DEFAULT '[]',
              redirect_uri TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS folders (
              id TEXT PRIMARY KEY,
              connection_id TEXT NOT NULL,
              provider_folder_id TEXT NOT NULL,
              name TEXT NOT NULL,
              canonical TEXT NOT NULL,
              folder_type TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(connection_id, canonical)
            );
            CREATE TABLE IF NOT EXISTS labels (
              id TEXT PRIMARY KEY,
              connection_id TEXT NOT NULL,
              provider_label_id TEXT NOT NULL,
              name TEXT NOT NULL,
              canonical TEXT NOT NULL,
              color TEXT NOT NULL DEFAULT '',
              UNIQUE(connection_id, canonical)
            );
            CREATE TABLE IF NOT EXISTS threads (
              id TEXT PRIMARY KEY,
              connection_id TEXT NOT NULL,
              provider_thread_id TEXT NOT NULL,
              subject TEXT NOT NULL,
              participants_json TEXT NOT NULL DEFAULT '[]',
              last_message_at TEXT NOT NULL,
              snippet TEXT NOT NULL DEFAULT '',
              unread INTEGER NOT NULL DEFAULT 0,
              starred INTEGER NOT NULL DEFAULT 0,
              labels_json TEXT NOT NULL DEFAULT '[]',
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              thread_id TEXT NOT NULL,
              provider_message_id TEXT NOT NULL,
              sender_json TEXT NOT NULL,
              recipients_json TEXT NOT NULL DEFAULT '[]',
              cc_json TEXT NOT NULL DEFAULT '[]',
              bcc_json TEXT NOT NULL DEFAULT '[]',
              sent_at TEXT NOT NULL,
              body_text TEXT NOT NULL DEFAULT '',
              body_html_sanitized TEXT NOT NULL DEFAULT '',
              body_html_original_bounded TEXT NOT NULL DEFAULT '',
              body_html_gmail_sanitized TEXT NOT NULL DEFAULT '',
              body_html_rendered TEXT NOT NULL DEFAULT '',
              render_policy_json TEXT NOT NULL DEFAULT '{}',
              headers_json TEXT NOT NULL DEFAULT '{}',
              has_attachments INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS attachments (
              id TEXT PRIMARY KEY,
              message_id TEXT NOT NULL,
              provider_attachment_id TEXT NOT NULL,
              filename TEXT NOT NULL,
              content_type TEXT NOT NULL DEFAULT '',
              size_bytes INTEGER NOT NULL DEFAULT 0,
              storage_state TEXT NOT NULL DEFAULT 'metadata_only',
              storage_ref_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS drafts (
              id TEXT PRIMARY KEY,
              connection_id TEXT NOT NULL,
              thread_id TEXT,
              to_json TEXT NOT NULL DEFAULT '[]',
              cc_json TEXT NOT NULL DEFAULT '[]',
              bcc_json TEXT NOT NULL DEFAULT '[]',
              reply_to_json TEXT NOT NULL DEFAULT '[]',
              subject TEXT NOT NULL,
              body_text TEXT NOT NULL,
              body_html TEXT NOT NULL DEFAULT '',
              workspace_attachments_json TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL,
              dirty INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              sent_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sync_state (
              connection_id TEXT PRIMARY KEY,
              last_sync_at TEXT,
              last_error TEXT,
              cursor TEXT
            );
            CREATE TABLE IF NOT EXISTS entity_links (
              id TEXT PRIMARY KEY,
              source_entity_type TEXT NOT NULL,
              source_entity_id TEXT NOT NULL,
              target_app_id TEXT NOT NULL,
              target_entity_type TEXT NOT NULL,
              target_entity_id TEXT NOT NULL,
              relation TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
              id TEXT PRIMARY KEY,
              action TEXT NOT NULL,
              target_type TEXT NOT NULL,
              target_id TEXT NOT NULL,
              detail_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_threads_connection ON threads(connection_id);
            CREATE INDEX IF NOT EXISTS idx_threads_updated ON threads(last_message_at);
            CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
            CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
            CREATE INDEX IF NOT EXISTS idx_drafts_updated ON drafts(updated_at);
            CREATE INDEX IF NOT EXISTS idx_entity_links_source ON entity_links(source_entity_type, source_entity_id);
            CREATE INDEX IF NOT EXISTS idx_entity_links_target ON entity_links(target_app_id, target_entity_type, target_entity_id);
        """)
        _ensure_column(db, "sync_state", "last_full_sync_at", "TEXT")
        _ensure_column(db, "sync_state", "last_incremental_sync_at", "TEXT")
        _ensure_column(db, "sync_state", "provider_history_id", "TEXT")
        _ensure_column(db, "connections", "settings_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(db, "oauth_credentials", "grant_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "messages", "body_html_sanitized", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "messages", "body_html_original_bounded", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "messages", "body_html_gmail_sanitized", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "messages", "body_html_rendered", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "messages", "render_policy_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(db, "messages", "body_render_mode", "TEXT NOT NULL DEFAULT 'plain'")
        _ensure_column(db, "messages", "body_preview", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "messages", "body_truncated", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "messages", "parts_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "messages", "inline_assets_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "drafts", "reply_to_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "drafts", "body_html", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "drafts", "workspace_attachments_json", "TEXT NOT NULL DEFAULT '[]'")
        _backfill_message_render_columns(db)
        db.execute(
            "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )
        _remove_mock_provider_rows(db)
        _migrate_legacy_gmail_cache_ids(db)


def health_payload(data_root: Path, *, initialize: bool = True) -> dict[str, object]:
    if initialize:
        ensure_schema(data_root)
    path = db_path(data_root)
    if not path.exists():
        return {
            "health_status": "missing_database",
            "database": path.name,
            "schema_version": "",
            "connection_count": 0,
            "thread_count": 0,
            "draft_count": 0,
        }
    try:
        with connect(data_root) as db:
            quick_check = db.execute("PRAGMA quick_check").fetchone()
            quick_check_value = quick_check[0] if quick_check else "missing"
            if quick_check_value != "ok":
                return _unhealthy_payload(path, "corrupt_database", str(quick_check_value))
            missing_tables = [
                table
                for table in REQUIRED_TABLES
                if db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is None
            ]
            if missing_tables:
                return _unhealthy_payload(path, "missing_tables", ",".join(missing_tables))
            version = db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
            connection_count = db.execute("SELECT COUNT(*) AS count FROM connections").fetchone()["count"]
            thread_count = db.execute("SELECT COUNT(*) AS count FROM threads").fetchone()["count"]
            draft_count = db.execute("SELECT COUNT(*) AS count FROM drafts WHERE status != 'sent'").fetchone()["count"]
    except sqlite3.DatabaseError as error:
        return _unhealthy_payload(path, "database_error", str(error))
    return {
        "health_status": "healthy",
        "schema_version": version["value"] if version else SCHEMA_VERSION,
        "database": path.name,
        "connection_count": connection_count,
        "thread_count": thread_count,
        "draft_count": draft_count,
    }


def oauth_flow_expiry() -> str:
    return (datetime.now(tz=UTC) + timedelta(minutes=15)).isoformat()


def _unhealthy_payload(path: Path, status: str, detail: str) -> dict[str, object]:
    return {
        "health_status": status,
        "health_detail": detail,
        "database": path.name,
        "schema_version": "",
        "connection_count": 0,
        "thread_count": 0,
        "draft_count": 0,
    }


def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _backfill_message_render_columns(db: sqlite3.Connection) -> None:
    legacy_policy = json.dumps(
        {
            "version": 0,
            "source": "legacy_body_html_sanitized",
            "rendered_from": "body_html_sanitized",
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    db.execute(
        """
        UPDATE messages
        SET body_html_gmail_sanitized = body_html_sanitized
        WHERE body_html_gmail_sanitized = ''
          AND body_html_sanitized != ''
        """
    )
    db.execute(
        """
        UPDATE messages
        SET body_html_rendered = COALESCE(NULLIF(body_html_gmail_sanitized, ''), body_html_sanitized)
        WHERE body_html_rendered = ''
          AND (body_html_gmail_sanitized != '' OR body_html_sanitized != '')
        """
    )
    db.execute(
        """
        UPDATE messages
        SET body_html_sanitized = body_html_rendered
        WHERE body_html_sanitized = ''
          AND body_html_rendered != ''
        """
    )
    db.execute(
        """
        UPDATE messages
        SET body_render_mode = 'html'
        WHERE body_render_mode = 'plain'
          AND body_html_rendered != ''
        """
    )
    db.execute(
        "UPDATE messages SET render_policy_json = ? WHERE render_policy_json = '' OR render_policy_json = '{}'",
        (legacy_policy,),
    )


def _remove_mock_provider_rows(db: sqlite3.Connection) -> None:
    connection_ids = [
        str(row["id"])
        for row in db.execute(
            """
            SELECT id
            FROM connections
            WHERE provider = 'mock'
               OR status = 'mock_connected'
               OR id = 'mail_connection_demo'
               OR email_address IN ('mock@example.com', 'demo@example.com')
            """
        ).fetchall()
    ]
    if not connection_ids:
        return
    thread_ids = _ids_for(db, "SELECT id FROM threads WHERE connection_id IN ({})", connection_ids)
    message_ids = _ids_for(db, "SELECT id FROM messages WHERE thread_id IN ({})", thread_ids)
    attachment_ids = _ids_for(db, "SELECT id FROM attachments WHERE message_id IN ({})", message_ids)
    draft_ids = _ids_for(db, "SELECT id FROM drafts WHERE connection_id IN ({}) OR thread_id IN ({})", connection_ids, thread_ids)
    entity_ids = {
        "mail_connection": connection_ids,
        "email_thread": thread_ids,
        "email_message": message_ids,
        "mail_attachment": attachment_ids,
        "mail_draft": draft_ids,
    }
    for entity_type, ids in entity_ids.items():
        _delete_entity_links(db, entity_type, ids)
        _delete_where_in(db, "audit_log", "target_id", ids)
    _delete_where_in(db, "attachments", "id", attachment_ids)
    _delete_where_in(db, "messages", "id", message_ids)
    _delete_where_in(db, "drafts", "id", draft_ids)
    _delete_where_in(db, "threads", "id", thread_ids)
    _delete_where_in(db, "folders", "connection_id", connection_ids)
    _delete_where_in(db, "labels", "connection_id", connection_ids)
    _delete_where_in(db, "sync_state", "connection_id", connection_ids)
    _delete_where_in(db, "oauth_credentials", "connection_id", connection_ids)
    _delete_where_in(db, "connections", "id", connection_ids)


def _ids_for(db: sqlite3.Connection, sql_template: str, *id_groups: list[str]) -> list[str]:
    if all(not ids for ids in id_groups):
        return []
    placeholders = [",".join("?" for _ in ids) if ids else "NULL" for ids in id_groups]
    params = [item for ids in id_groups for item in ids]
    return [str(row["id"]) for row in db.execute(sql_template.format(*placeholders), params).fetchall()]


def _delete_entity_links(db: sqlite3.Connection, entity_type: str, ids: list[str]) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    db.execute(
        f"DELETE FROM entity_links WHERE source_entity_type = ? AND source_entity_id IN ({placeholders})",
        [entity_type, *ids],
    )
    db.execute(
        f"DELETE FROM entity_links WHERE target_app_id = 'mail' AND target_entity_type = ? AND target_entity_id IN ({placeholders})",
        [entity_type, *ids],
    )


def _delete_where_in(db: sqlite3.Connection, table: str, column: str, ids: list[str]) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    db.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", ids)


def _migrate_legacy_gmail_cache_ids(db: sqlite3.Connection) -> None:
    rows = db.execute(
        """
        SELECT threads.id, threads.connection_id, threads.provider_thread_id
        FROM threads JOIN connections ON threads.connection_id = connections.id
        WHERE connections.provider = 'gmail'
        """
    ).fetchall()
    for row in rows:
        new_id = _local_gmail_thread_id(row["connection_id"], row["provider_thread_id"])
        if row["id"] != new_id and _rename_entity_id(db, "email_thread", "threads", row["id"], new_id):
            db.execute("UPDATE messages SET thread_id = ? WHERE thread_id = ?", (new_id, row["id"]))
            db.execute("UPDATE drafts SET thread_id = ? WHERE thread_id = ?", (new_id, row["id"]))

    rows = db.execute(
        """
        SELECT messages.id, messages.provider_message_id, threads.connection_id
        FROM messages JOIN threads ON messages.thread_id = threads.id
        JOIN connections ON threads.connection_id = connections.id
        WHERE connections.provider = 'gmail'
        """
    ).fetchall()
    for row in rows:
        new_id = _local_gmail_message_id(row["connection_id"], row["provider_message_id"])
        if row["id"] != new_id and _rename_entity_id(db, "email_message", "messages", row["id"], new_id):
            db.execute("UPDATE attachments SET message_id = ? WHERE message_id = ?", (new_id, row["id"]))

    rows = db.execute(
        """
        SELECT attachments.id, attachments.provider_attachment_id, messages.provider_message_id, threads.connection_id
        FROM attachments JOIN messages ON attachments.message_id = messages.id
        JOIN threads ON messages.thread_id = threads.id
        JOIN connections ON threads.connection_id = connections.id
        WHERE connections.provider = 'gmail'
        """
    ).fetchall()
    for row in rows:
        new_id = _local_gmail_attachment_id(row["connection_id"], row["provider_message_id"], row["provider_attachment_id"])
        if row["id"] != new_id:
            _rename_entity_id(db, "mail_attachment", "attachments", row["id"], new_id)


def _rename_entity_id(db: sqlite3.Connection, entity_type: str, table: str, old_id: str, new_id: str) -> bool:
    if db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (new_id,)).fetchone() is not None:
        return False
    db.execute(f"UPDATE {table} SET id = ? WHERE id = ?", (new_id, old_id))
    db.execute("UPDATE audit_log SET target_id = ? WHERE target_type = ? AND target_id = ?", (new_id, entity_type, old_id))
    db.execute("UPDATE entity_links SET source_entity_id = ? WHERE source_entity_type = ? AND source_entity_id = ?", (new_id, entity_type, old_id))
    db.execute(
        """
        UPDATE entity_links
        SET target_entity_id = ?
        WHERE target_app_id = 'mail' AND target_entity_type = ? AND target_entity_id = ?
        """,
        (new_id, entity_type, old_id),
    )
    return True


def _local_gmail_thread_id(connection_id: object, provider_thread_id: object) -> str:
    return f"email_thread_gmail_{_safe_id(str(connection_id))}_{_safe_id(str(provider_thread_id))}"


def _local_gmail_message_id(connection_id: object, provider_message_id: object) -> str:
    return f"email_message_gmail_{_safe_id(str(connection_id))}_{_safe_id(str(provider_message_id))}"


def _local_gmail_attachment_id(connection_id: object, provider_message_id: object, provider_attachment_id: object) -> str:
    return f"mail_attachment_gmail_{_safe_id(str(connection_id))}_{_safe_id(str(provider_message_id))}_{_safe_id(str(provider_attachment_id))}"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "unknown"
