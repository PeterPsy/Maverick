"""SQLite adapter for Video Studio's workspace-owned foundation database."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any

from .migrations import MigrationError, apply_migrations, discover_migrations
from .paths import DataRootError, safe_data_path


APP_DATABASE_NAME = "app.db"
LATEST_SCHEMA_VERSION = 2
DOMAIN_TABLES = (
    "projects",
    "project_revisions",
    "project_branches",
    "project_assets",
    "media_assets",
    "media_derivatives",
    "analysis_jobs",
    "analysis_artifacts",
    "media_segments",
    "transcript_segments",
    "transcript_words",
    "speaker_turns",
    "ocr_spans",
    "semantic_documents",
    "embedding_records",
    "edit_sessions",
    "edit_proposals",
    "edit_operations",
    "render_jobs",
    "render_artifacts",
    "templates",
    "style_recipes",
    "audit_events",
)
REVISION_ENGINE_TABLES = (
    "project_projections",
    "project_revision_navigation",
    "project_operation_batches",
    "project_autosaves",
    "project_outbox",
)
FOUNDATION_TABLES = (
    "app_metadata",
    "schema_migrations",
    *DOMAIN_TABLES,
    *REVISION_ENGINE_TABLES,
)
LAYOUT_DIRECTORIES = (
    "migrations",
    "project-snapshots",
    "indices/text",
    "indices/vector",
    "cache/probes",
    "cache/proxies",
    "cache/thumbnails",
    "cache/waveforms",
    "cache/frames",
    "cache/model-results",
    "cache/remotion-bundles",
    "jobs/logs",
    "jobs/staging",
    "models/manifests",
    "audit",
    "tmp",
)


class FoundationDatabaseError(RuntimeError):
    """Stable application error for database and schema failures."""


class FoundationDatabase:
    """Own connection policy, migrations, health, and schema inspection."""

    def __init__(
        self,
        data_root: str | Path,
        *,
        migrations_root: Path | None = None,
        create_data_root: bool = True,
    ) -> None:
        try:
            self.database_path = safe_data_path(
                data_root,
                APP_DATABASE_NAME,
                create_root=create_data_root,
            )
        except DataRootError as error:
            raise FoundationDatabaseError(str(error)) from error
        self.data_root = self.database_path.parent
        self.migrations_root = migrations_root or Path(__file__).resolve().parents[2] / "migrations"

    def prepare_layout(self) -> None:
        """Create only the documented app-owned directory layout."""
        for relative_path in LAYOUT_DIRECTORIES:
            try:
                path = safe_data_path(self.data_root, relative_path)
            except DataRootError as error:
                raise FoundationDatabaseError(str(error)) from error
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise FoundationDatabaseError(
                    "Video Studio app data layout could not be prepared."
                ) from error

    def connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        """Open a configured SQLite connection with explicit access mode."""
        target = (
            f"{self.database_path.as_uri()}?mode=ro"
            if read_only
            else str(self.database_path)
        )
        connection = sqlite3.connect(target, timeout=30, uri=read_only)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
            if read_only:
                connection.execute("PRAGMA query_only = ON")
            else:
                _configure_journal_mode(connection)
                connection.execute("PRAGMA synchronous = NORMAL")
            if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
                raise FoundationDatabaseError(
                    "SQLite foreign key enforcement is unavailable."
                )
        except Exception:
            connection.close()
            raise
        return connection

    def migrate(self) -> dict[str, Any]:
        """Prepare the layout and idempotently apply every source migration."""
        self.prepare_layout()
        try:
            migrations = discover_migrations(self.migrations_root)
            if migrations[-1].version != LATEST_SCHEMA_VERSION:
                raise MigrationError("Migration source and application schema versions disagree.")
            with closing(self.connect()) as connection:
                applied = apply_migrations(connection, migrations)
                status = self._schema_status(connection)
        except FoundationDatabaseError:
            raise
        except (MigrationError, sqlite3.Error, ValueError) as error:
            raise FoundationDatabaseError(str(error)) from error
        return {**status, "applied_migrations": applied}

    def schema_status(self) -> dict[str, Any]:
        """Return redaction-safe schema metadata without exposing host paths."""
        if not self.database_path.is_file():
            raise FoundationDatabaseError("Video Studio database is not installed.")
        try:
            with closing(self.connect(read_only=True)) as connection:
                return self._schema_status(connection)
        except FoundationDatabaseError:
            raise
        except (MigrationError, sqlite3.Error, ValueError) as error:
            raise FoundationDatabaseError(f"Unable to inspect Video Studio database: {error}") from error

    def health(self) -> dict[str, Any]:
        """Verify schema, referential integrity, and a rollback-only write."""
        if not self.database_path.is_file():
            raise FoundationDatabaseError("Video Studio database is not installed.")
        try:
            with closing(self.connect()) as connection:
                status = self._schema_status(connection)
                quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
                foreign_key_violations = list(connection.execute("PRAGMA foreign_key_check"))
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE app_metadata SET value = value WHERE key = 'schema_version'"
                )
                connection.rollback()
        except FoundationDatabaseError:
            raise
        except (MigrationError, sqlite3.Error, ValueError) as error:
            raise FoundationDatabaseError(f"Video Studio database health check failed: {error}") from error
        if quick_check != ["ok"]:
            raise FoundationDatabaseError("Video Studio database integrity check failed.")
        if foreign_key_violations:
            raise FoundationDatabaseError("Video Studio database has foreign key violations.")
        if status["schema_version"] != LATEST_SCHEMA_VERSION:
            raise FoundationDatabaseError("Video Studio database schema is not current.")
        return {
            "status": "healthy",
            "schema_version": status["schema_version"],
            "journal_mode": status["journal_mode"],
            "foreign_keys": True,
            "read_write": True,
        }

    def _schema_status(self, connection: sqlite3.Connection) -> dict[str, Any]:
        tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_schema
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]
        migrations = [
            {"version": int(row[0]), "name": str(row[1]), "checksum": str(row[2])}
            for row in connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            )
        ]
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        metadata_row = connection.execute(
            "SELECT value FROM app_metadata WHERE key = 'schema_version'"
        ).fetchone()
        metadata_schema_version = int(metadata_row[0]) if metadata_row is not None else 0
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        expected_migrations = discover_migrations(self.migrations_root)
        expected_history = [
            {
                "version": migration.version,
                "name": migration.name,
                "checksum": migration.checksum,
            }
            for migration in expected_migrations
        ]
        missing_tables = sorted(set(FOUNDATION_TABLES) - set(tables))
        if missing_tables:
            raise FoundationDatabaseError(
                "Video Studio database is missing required schema tables."
            )
        if migrations != expected_history:
            raise FoundationDatabaseError(
                "Video Studio database migration history does not match the app source."
            )
        if schema_version != metadata_schema_version:
            raise FoundationDatabaseError(
                "Video Studio database schema metadata is inconsistent."
            )
        return {
            "schema_version": schema_version,
            "latest_schema_version": LATEST_SCHEMA_VERSION,
            "metadata_schema_version": metadata_schema_version,
            "journal_mode": journal_mode,
            "tables": tables,
            "table_count": len(tables),
            "domain_aggregate_count": len(DOMAIN_TABLES),
            "migrations": migrations,
        }


def _configure_journal_mode(connection: sqlite3.Connection) -> str:
    """Prefer WAL and deterministically fall back to the rollback journal."""
    try:
        row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        mode = str(row[0]).lower() if row is not None else ""
    except sqlite3.DatabaseError:
        mode = ""
    if mode == "wal":
        return mode
    row = connection.execute("PRAGMA journal_mode = DELETE").fetchone()
    fallback = str(row[0]).lower() if row is not None else ""
    if fallback != "delete":
        raise FoundationDatabaseError(
            "SQLite WAL and rollback journal modes are unavailable."
        )
    return fallback
