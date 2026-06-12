"""SQLite database helpers for Website Studio."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from collections.abc import Iterator
from pathlib import Path
import sqlite3


SCHEMA_VERSION = "3"
REFERENCE_ENTITIES = ["site", "page", "route", "component", "asset", "revision", "publish_request"]


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
              source_profile_json TEXT NOT NULL DEFAULT '{}',
              source_version TEXT NOT NULL DEFAULT '',
              source_artifact_ref_json TEXT NOT NULL DEFAULT '{}',
              default_environment_id TEXT NOT NULL DEFAULT '',
              working_branch TEXT NOT NULL DEFAULT '',
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
              approval_id TEXT NOT NULL DEFAULT '',
              environment_id TEXT NOT NULL DEFAULT 'env_preview',
              build_id TEXT NOT NULL DEFAULT '',
              preview_ref TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_publish_requests_site_updated ON publish_requests(site_id, updated_at);
            CREATE TABLE IF NOT EXISTS environments (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              kind TEXT NOT NULL,
              base_url TEXT NOT NULL DEFAULT '',
              publish_target_id TEXT NOT NULL DEFAULT '',
              requires_approval INTEGER NOT NULL DEFAULT 1,
              last_deployment_id TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_environments_site_kind ON environments(site_id, kind);
            CREATE TABLE IF NOT EXISTS publish_targets (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              environment_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              config_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_publish_targets_site ON publish_targets(site_id);
            CREATE TABLE IF NOT EXISTS approval_events (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              action TEXT NOT NULL,
              target_id TEXT NOT NULL,
              status TEXT NOT NULL,
              approved_by TEXT NOT NULL,
              approval_note TEXT NOT NULL DEFAULT '',
              used_at TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_approval_events_target ON approval_events(site_id, action, target_id, status);
            CREATE TABLE IF NOT EXISTS builds (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              status TEXT NOT NULL,
              runtime_kind TEXT NOT NULL DEFAULT '',
              preview_url TEXT NOT NULL DEFAULT '',
              artifact_ref_json TEXT NOT NULL DEFAULT '{}',
              source_profile_json TEXT NOT NULL DEFAULT '{}',
              route_count INTEGER NOT NULL DEFAULT 0,
              asset_count INTEGER NOT NULL DEFAULT 0,
              warnings_json TEXT NOT NULL DEFAULT '[]',
              missing_requirements_json TEXT NOT NULL DEFAULT '[]',
              logs_summary TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_builds_site_created ON builds(site_id, created_at);
            CREATE TABLE IF NOT EXISTS sync_runs (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              source_provider TEXT NOT NULL,
              status TEXT NOT NULL,
              branch TEXT NOT NULL DEFAULT '',
              files_changed_count INTEGER NOT NULL DEFAULT 0,
              conflicts_json TEXT NOT NULL DEFAULT '[]',
              source_profile_json TEXT NOT NULL DEFAULT '{}',
              logs_summary TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sync_runs_site_created ON sync_runs(site_id, created_at);
            CREATE TABLE IF NOT EXISTS previews (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              route TEXT NOT NULL,
              page_id TEXT NOT NULL DEFAULT '',
              build_id TEXT NOT NULL DEFAULT '',
              runtime_kind TEXT NOT NULL DEFAULT '',
              preview_url TEXT NOT NULL DEFAULT '',
              warnings_json TEXT NOT NULL DEFAULT '[]',
              missing_requirements_json TEXT NOT NULL DEFAULT '[]',
              artifact_ref_json TEXT NOT NULL DEFAULT '{}',
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_previews_site_created ON previews(site_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_previews_site_route_created ON previews(site_id, route, created_at);
            CREATE TABLE IF NOT EXISTS runtime_sessions (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              preview_id TEXT NOT NULL DEFAULT '',
              build_id TEXT NOT NULL DEFAULT '',
              runtime_kind TEXT NOT NULL,
              status TEXT NOT NULL,
              preview_url TEXT NOT NULL DEFAULT '',
              route TEXT NOT NULL DEFAULT '/',
              health_json TEXT NOT NULL DEFAULT '{}',
              missing_requirements_json TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runtime_sessions_site_created ON runtime_sessions(site_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_runtime_sessions_site_route_created ON runtime_sessions(site_id, route, created_at);
            CREATE TABLE IF NOT EXISTS preview_reports (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              preview_id TEXT NOT NULL DEFAULT '',
              route TEXT NOT NULL DEFAULT '/',
              status TEXT NOT NULL,
              report_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_preview_reports_site_created ON preview_reports(site_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_preview_reports_site_route_created ON preview_reports(site_id, route, created_at);
            CREATE INDEX IF NOT EXISTS idx_preview_reports_preview_created ON preview_reports(preview_id, created_at);
            CREATE TABLE IF NOT EXISTS deployments (
              id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
              environment_id TEXT NOT NULL,
              publish_request_id TEXT NOT NULL DEFAULT '',
              revision_id TEXT NOT NULL,
              status TEXT NOT NULL,
              mode TEXT NOT NULL,
              source_ref_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_deployments_site_created ON deployments(site_id, created_at);
            CREATE TABLE IF NOT EXISTS git_connections (
              id TEXT PRIMARY KEY,
              site_id TEXT REFERENCES sites(id) ON DELETE SET NULL,
              provider TEXT NOT NULL,
              owner TEXT NOT NULL,
              repo TEXT NOT NULL,
              repository_url TEXT NOT NULL,
              base_branch TEXT NOT NULL DEFAULT 'main',
              auth_mode TEXT NOT NULL,
              secret_logical_name TEXT NOT NULL DEFAULT '',
              github_app_id TEXT NOT NULL DEFAULT '',
              github_installation_id TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_git_connections_repo ON git_connections(provider, owner, repo);
            CREATE INDEX IF NOT EXISTS idx_git_connections_site ON git_connections(site_id);
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
        _ensure_column(db, "sites", "source_profile_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(db, "sites", "source_version", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "sites", "source_artifact_ref_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(db, "sites", "default_environment_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "sites", "working_branch", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "pages", "asset_refs_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "pages", "warnings_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "publish_requests", "approval_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "publish_requests", "environment_id", "TEXT NOT NULL DEFAULT 'env_preview'")
        _ensure_column(db, "publish_requests", "build_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "environments", "publish_target_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "environments", "last_deployment_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "builds", "runtime_kind", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "builds", "preview_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "builds", "artifact_ref_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(db, "builds", "missing_requirements_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "previews", "runtime_kind", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "previews", "preview_url", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "previews", "warnings_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "previews", "missing_requirements_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "previews", "artifact_ref_json", "TEXT NOT NULL DEFAULT '{}'")
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
