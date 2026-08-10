"""SQLite migration, integrity, and path-confinement tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from foundation.database import (  # noqa: E402
    DOMAIN_TABLES,
    FOUNDATION_TABLES,
    LAYOUT_DIRECTORIES,
    FoundationDatabase,
    FoundationDatabaseError,
    _configure_journal_mode,
)
from foundation.migrations import (  # noqa: E402
    MigrationError,
    apply_migrations,
    discover_migrations,
)
from foundation.paths import DataRootError, safe_data_path  # noqa: E402


MIGRATIONS_ROOT = APP_ROOT / "migrations"
FOUNDATION_CHECKSUM = "6aa8d20f562311380f9137f5c21430ae431a71d17bafead92b6fab1087af8552"


class FoundationDatabaseTest(unittest.TestCase):
    def test_version_one_database_upgrades_without_mutating_foundation_checksum(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            migration_root = root / "migrations"
            migration_root.mkdir()
            shutil.copy2(MIGRATIONS_ROOT / "0001_foundation.sql", migration_root)
            connection = sqlite3.connect(root / "app.db")
            try:
                first = discover_migrations(migration_root)
                self.assertEqual(first[0].checksum, FOUNDATION_CHECKSUM)
                self.assertEqual(apply_migrations(connection, first), [1])
                shutil.copy2(MIGRATIONS_ROOT / "0002_project_revision_engine.sql", migration_root)
                self.assertEqual(apply_migrations(connection, discover_migrations(migration_root)), [2])
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT name FROM sqlite_schema WHERE name = 'project_outbox'"
                    ).fetchone()
                )
            finally:
                connection.close()

    def test_migration_is_complete_transactional_and_idempotent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data" / "video-studio"
            database = FoundationDatabase(data_root)

            first = database.migrate()
            second = database.migrate()
            health = database.health()

            self.assertEqual(first["applied_migrations"], [1, 2])
            self.assertEqual(second["applied_migrations"], [])
            self.assertEqual(first["domain_aggregate_count"], 23)
            self.assertEqual(set(first["tables"]), set(FOUNDATION_TABLES))
            self.assertEqual(len(DOMAIN_TABLES), 23)
            self.assertEqual(health["status"], "healthy")
            self.assertIn(health["journal_mode"], {"wal", "delete"})
            for relative_path in LAYOUT_DIRECTORIES:
                self.assertTrue((data_root / relative_path).is_dir(), relative_path)

            with closing(database.connect()) as connection:
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                migration_count = connection.execute(
                    "SELECT COUNT(*) FROM schema_migrations"
                ).fetchone()[0]
                self.assertEqual(migration_count, 2)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO projects(
                            project_id, name, created_at, updated_at
                        ) VALUES ('bad-json-parent', 'Project', 'now', 'now')
                        """
                    )
                    connection.execute(
                        """
                        INSERT INTO project_revisions(
                            revision_id, project_id, schema_version, project_ir_json,
                            author_kind, digest, created_at
                        ) VALUES ('bad-json', 'bad-json-parent', 1, '{', 'user', 'digest', 'now')
                        """
                    )

    def test_failed_migration_rolls_back_every_statement(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            migration_root = root / "migrations"
            migration_root.mkdir()
            shutil.copy2(MIGRATIONS_ROOT / "0001_foundation.sql", migration_root)
            database_path = root / "app.db"
            connection = sqlite3.connect(database_path)
            try:
                apply_migrations(connection, discover_migrations(migration_root))
                (migration_root / "0002_broken.sql").write_text(
                    "CREATE TABLE should_rollback(value TEXT) STRICT;\n"
                    "INSERT INTO missing_table(value) VALUES ('fail');\n",
                    encoding="utf-8",
                )
                with self.assertRaises(MigrationError):
                    apply_migrations(connection, discover_migrations(migration_root))
                table = connection.execute(
                    "SELECT name FROM sqlite_schema WHERE name = 'should_rollback'"
                ).fetchone()
                self.assertIsNone(table)
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                    1,
                )
            finally:
                connection.close()

    def test_applied_migration_checksum_is_immutable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            migration_root = Path(temp_dir) / "migrations"
            migration_root.mkdir()
            target = migration_root / "0001_foundation.sql"
            shutil.copy2(MIGRATIONS_ROOT / "0001_foundation.sql", target)
            connection = sqlite3.connect(":memory:")
            try:
                apply_migrations(connection, discover_migrations(migration_root))
                target.write_text(target.read_text(encoding="utf-8") + "\n-- drift\n", encoding="utf-8")
                with self.assertRaisesRegex(MigrationError, "checksum"):
                    apply_migrations(connection, discover_migrations(migration_root))
            finally:
                connection.close()

    def test_health_rejects_inconsistent_schema_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database = FoundationDatabase(Path(temp_dir) / "data")
            database.migrate()
            with closing(database.connect()) as connection:
                connection.execute(
                    "UPDATE app_metadata SET value = '3' WHERE key = 'schema_version'"
                )
                connection.commit()
            with self.assertRaisesRegex(FoundationDatabaseError, "inconsistent"):
                database.health()

    def test_paths_reject_absolute_traversal_and_symlinks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "data"
            outside = Path(temp_dir) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(DataRootError):
                safe_data_path(root, "../outside/file")
            with self.assertRaises(DataRootError):
                safe_data_path(root, outside / "file")
            with self.assertRaises(DataRootError):
                safe_data_path(root, "link/file")
            with self.assertRaises(DataRootError):
                safe_data_path("relative/root", "app.db")
            with self.assertRaises(DataRootError):
                safe_data_path(root / ".." / "outside", "app.db")
            self.assertEqual(safe_data_path(root, "nested/file"), root / "nested" / "file")

    def test_migrate_writes_nothing_outside_supplied_data_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            boundary = Path(temp_dir)
            data_root = boundary / "data-root"
            sentinel = boundary / "sentinel.txt"
            sentinel.write_text("unchanged", encoding="utf-8")

            FoundationDatabase(data_root).migrate()

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual({path.name for path in boundary.iterdir()}, {"data-root", "sentinel.txt"})

    def test_wal_failure_uses_checked_delete_fallback(self) -> None:
        class Cursor:
            def __init__(self, value: str) -> None:
                self.value = value

            def fetchone(self) -> tuple[str]:
                return (self.value,)

        class Connection:
            def __init__(self) -> None:
                self.statements: list[str] = []

            def execute(self, statement: str) -> Cursor:
                self.statements.append(statement)
                if statement.endswith("WAL"):
                    raise sqlite3.DatabaseError("wal unavailable")
                return Cursor("delete")

        connection = Connection()
        self.assertEqual(_configure_journal_mode(connection), "delete")  # type: ignore[arg-type]
        self.assertEqual(
            connection.statements,
            ["PRAGMA journal_mode = WAL", "PRAGMA journal_mode = DELETE"],
        )


if __name__ == "__main__":
    unittest.main()
