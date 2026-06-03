"""SQLite database helpers for Website Studio."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from collections.abc import Iterator
from pathlib import Path
import sqlite3


SCHEMA_VERSION = "1"
REFERENCE_ENTITIES = ["site", "page", "route", "asset", "revision", "publish_request"]


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def db_path(data_root: Path) -> Path:
    return data_root / "app.sqlite"


@contextmanager
def connect(data_root: Path) -> Iterator[sqlite3.Connection]:
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(data_root))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def ensure_schema(data_root: Path) -> None:
    with connect(data_root) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sites (
              id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              slug TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL,
              primary_domain TEXT NOT NULL DEFAULT '',
              source_provider TEXT NOT NULL,
              source_label TEXT NOT NULL DEFAULT '',
              source_shape TEXT NOT NULL DEFAULT '',
              source_artifact_ref_json TEXT NOT NULL DEFAULT '{}',
              active_revision_id TEXT,
              published_revision_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              archived_at TEXT
            );
            CREATE TABLE IF NOT EXISTS pages (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              route TEXT NOT NULL,
              title TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              source_files_json TEXT NOT NULL,
              asset_refs_json TEXT NOT NULL DEFAULT '[]',
              warnings_json TEXT NOT NULL DEFAULT '[]',
              seo_json TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL,
              deleted_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pages_site_route ON pages(site_id, route);
            CREATE INDEX IF NOT EXISTS idx_pages_site_updated ON pages(site_id, updated_at);
            CREATE TABLE IF NOT EXISTS routes (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              route TEXT NOT NULL,
              page_id TEXT,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              source_files_json TEXT NOT NULL,
              warnings_json TEXT NOT NULL DEFAULT '[]',
              updated_at TEXT NOT NULL,
              deleted_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_routes_site_route ON routes(site_id, route);
            CREATE TABLE IF NOT EXISTS assets (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              path TEXT NOT NULL,
              kind TEXT NOT NULL,
              content_type TEXT NOT NULL,
              size_bytes INTEGER NOT NULL,
              sha256 TEXT NOT NULL,
              referenced_by_json TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL,
              warnings_json TEXT NOT NULL DEFAULT '[]',
              updated_at TEXT NOT NULL,
              deleted_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_site_path ON assets(site_id, path);
            CREATE TABLE IF NOT EXISTS revisions (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              label TEXT NOT NULL,
              source TEXT NOT NULL,
              summary TEXT NOT NULL DEFAULT '',
              snapshot_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_revisions_site_created ON revisions(site_id, created_at);
            CREATE TABLE IF NOT EXISTS changesets (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              base_revision_id TEXT,
              status TEXT NOT NULL,
              summary TEXT NOT NULL DEFAULT '',
              files_changed_count INTEGER NOT NULL DEFAULT 0,
              created_via TEXT NOT NULL DEFAULT 'user',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_changesets_site_updated ON changesets(site_id, updated_at);
            CREATE TABLE IF NOT EXISTS publish_requests (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              changeset_id TEXT,
              status TEXT NOT NULL,
              diff_summary TEXT NOT NULL DEFAULT '',
              approval_policy TEXT NOT NULL DEFAULT 'human_required',
              requested_by TEXT NOT NULL DEFAULT 'workspace',
              approved_by TEXT NOT NULL DEFAULT '',
              preview_ref TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_publish_requests_site_updated ON publish_requests(site_id, updated_at);
            CREATE TABLE IF NOT EXISTS audit_events (
              id TEXT PRIMARY KEY,
              site_id TEXT,
              event_type TEXT NOT NULL,
              summary TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
        """)
        _ensure_column(db, "sites", "source_shape", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "sites", "source_artifact_ref_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(db, "pages", "asset_refs_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "pages", "warnings_json", "TEXT NOT NULL DEFAULT '[]'")
        db.execute(
            "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )


def health_payload(data_root: Path) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        version = db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
    return {"schema_version": version["value"] if version else SCHEMA_VERSION, "database": "app.sqlite"}


def _ensure_column(db: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
