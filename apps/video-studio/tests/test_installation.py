"""Generic installation-level registration and binding test."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from core.apps.builtin_apps import register_and_install_builtin_apps
from core.apps.errors import AppLifecycleError, WorkspaceAppBindingNotFoundError
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.store import AppCollections, AppDocumentStore
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore
from tests.support.collections import FakeCollection


APP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = APP_ROOT.parents[1]
MIGRATION_HISTORY = [
    (1, "foundation", "6aa8d20f562311380f9137f5c21430ae431a71d17bafead92b6fab1087af8552"),
    (
        2,
        "project_revision_engine",
        "ce6b31746ea39f21f3e14b7acfe5546f7d1f6715d50c50bb78cf1fd6f2d5bbfc",
    ),
    (
        3,
        "revision_integrity",
        "1fb29cdeb54c4a8b70069c4671296fa89d004607e2b5a4271c5bd8abac3ca035",
    ),
]


def _store() -> AppDocumentStore:
    return AppDocumentStore(
        AppCollections(
            app_sources=FakeCollection(),
            workspace_local_app_projects=FakeCollection(),
            workspace_app_bindings=FakeCollection(),
            workspace_app_dependency_selections=FakeCollection(),
        )
    )


def _workspace_store() -> WorkspaceDocumentStore:
    return WorkspaceDocumentStore(
        WorkspaceCollections(
            workspaces=FakeCollection(),
            memberships=FakeCollection(),
            governance=FakeCollection(),
            quotas=FakeCollection(),
            active_workspace_selections=FakeCollection(),
        )
    )


class InstallationLevelRegistrationTest(unittest.TestCase):
    def test_source_registration_and_workspace_binding_remain_distinct(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repository = self._temporary_repository(Path(temp_dir))
            store = _store()
            source_root = repository / "apps" / "video-studio"

            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(source_root),
            )

            self.assertEqual(source.app_id, "video-studio")
            self.assertEqual(source.source_kind, "platform")
            self.assertEqual(source.contract.distribution.mode, "source_available")
            with self.assertRaises(WorkspaceAppBindingNotFoundError):
                store.get_workspace_app_binding(
                    workspace_id="default",
                    app_id="video-studio",
                )
            self.assertEqual(store.list_workspace_local_app_projects("default"), [])

            first = install_store_app(
                store,
                source_id=source.source_id,
                workspace_id="default",
                start_path=repository,
            )
            second = install_store_app(
                store,
                source_id=source.source_id,
                workspace_id="default",
                start_path=repository,
            )

            self.assertEqual(first.status, "enabled")
            self.assertEqual(second.status, "enabled")
            self.assertEqual(second.source_kind, "platform")
            self.assertEqual(second.public_app_id, "video-studio")
            self.assertEqual(second.local_app_id, "video-studio")
            data_root = repository / "workspaces" / "default" / "data" / "video-studio"
            self.assertEqual(Path(second.data_root), data_root)
            self.assertTrue((data_root / "app.db").is_file())
            self.assertFalse(
                (repository / "workspaces" / "default" / "apps" / "video-studio").exists()
            )
            marker = json.loads((data_root / ".maverick-app.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["app_id"], "video-studio")
            self.assertEqual(marker["app_version"], "0.2.0")
            self.assertEqual(marker["data_schema_version"], "3")
            with closing(sqlite3.connect(data_root / "app.db")) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                    3,
                )

    def test_builtin_bootstrap_upgrades_schema_one_source_and_is_idempotent(self) -> None:
        installed_at = datetime(2026, 1, 1, tzinfo=UTC)
        upgraded_at = datetime(2026, 1, 2, tzinfo=UTC)
        with TemporaryDirectory() as temp_dir:
            repository = self._temporary_repository(Path(temp_dir))
            app_store = _store()
            workspace_store = _workspace_store()
            source_root = repository / "apps" / "video-studio"
            self._make_schema_one_source(source_root)

            old_source = register_app_source_from_contract(
                app_store,
                source_kind="platform",
                source_path=str(source_root),
                now=installed_at,
            )
            old_binding = install_store_app(
                app_store,
                source_id=old_source.source_id,
                workspace_id="default",
                start_path=repository,
                now=installed_at,
            )
            data_root = repository / "workspaces" / "default" / "data" / "video-studio"
            database_path = data_root / "app.db"

            self.assertEqual(old_source.source_id, "platform:video-studio:0.1.0")
            self.assertEqual(old_binding.active_version, "0.1.0")
            self.assertEqual(old_binding.source_record_id, old_source.source_id)
            self._assert_marker(data_root, app_version="0.1.0", schema_version="1")
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(self._migration_history(connection), MIGRATION_HISTORY[:1])
                connection.execute(
                    """
                    INSERT INTO projects(project_id, name, description, created_at, updated_at)
                    VALUES ('project-before-upgrade', 'Preserved project', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                    """
                )
                connection.commit()

            self._replace_with_current_source(source_root)
            ensured = register_and_install_builtin_apps(
                app_store,
                workspace_store,
                start_path=repository,
                now=upgraded_at,
            )

            self.assertEqual(ensured, ["video-studio"])
            sources = sorted(app_store.list_app_sources(), key=lambda source: source.version)
            self.assertEqual([source.version for source in sources], ["0.1.0", "0.2.0"])
            self.assertEqual(sources[1].source_id, "platform:video-studio:0.2.0")
            binding = app_store.get_workspace_app_binding(
                workspace_id="default",
                app_id="video-studio",
            )
            self.assertEqual(binding.status, "enabled")
            self.assertEqual(binding.active_version, "0.2.0")
            self.assertEqual(binding.source_record_id, sources[1].source_id)
            self._assert_marker(data_root, app_version="0.2.0", schema_version="3")
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(
                    connection.execute(
                        "SELECT value FROM app_metadata WHERE key = 'schema_version'"
                    ).fetchone()[0],
                    "3",
                )
                history_before_retry = self._migration_history(connection)
                self.assertEqual(history_before_retry, MIGRATION_HISTORY)
                self.assertEqual(
                    connection.execute(
                        "SELECT name FROM projects WHERE project_id = 'project-before-upgrade'"
                    ).fetchone()[0],
                    "Preserved project",
                )

            marker_before_retry = (data_root / ".maverick-app.json").read_bytes()
            binding_before_retry = binding
            self.assertEqual(
                register_and_install_builtin_apps(
                    app_store,
                    workspace_store,
                    start_path=repository,
                    now=upgraded_at,
                ),
                ["video-studio"],
            )

            self.assertEqual(len(app_store.list_app_sources()), 2)
            self.assertEqual(
                app_store.get_workspace_app_binding(
                    workspace_id="default",
                    app_id="video-studio",
                ),
                binding_before_retry,
            )
            self.assertEqual((data_root / ".maverick-app.json").read_bytes(), marker_before_retry)
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(self._migration_history(connection), history_before_retry)

    def test_failed_builtin_upgrade_does_not_publish_schema_three_binding(self) -> None:
        installed_at = datetime(2026, 2, 1, tzinfo=UTC)
        upgraded_at = datetime(2026, 2, 2, tzinfo=UTC)
        with TemporaryDirectory() as temp_dir:
            repository = self._temporary_repository(Path(temp_dir))
            app_store = _store()
            workspace_store = _workspace_store()
            source_root = repository / "apps" / "video-studio"
            self._make_schema_one_source(source_root)

            old_source = register_app_source_from_contract(
                app_store,
                source_kind="platform",
                source_path=str(source_root),
                now=installed_at,
            )
            old_binding = install_store_app(
                app_store,
                source_id=old_source.source_id,
                workspace_id="default",
                start_path=repository,
                now=installed_at,
            )
            data_root = repository / "workspaces" / "default" / "data" / "video-studio"
            database_path = data_root / "app.db"
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    """
                    INSERT INTO projects(project_id, name, description, created_at, updated_at)
                    VALUES ('project-before-failure', 'Still present', '', '2026-02-01T00:00:00Z', '2026-02-01T00:00:00Z')
                    """
                )
                connection.commit()
            marker_before_upgrade = (data_root / ".maverick-app.json").read_bytes()

            self._replace_with_current_source(source_root)
            migration = source_root / "migrations" / "0002_project_revision_engine.sql"
            migration.write_text(
                migration.read_text(encoding="utf-8")
                + "\nCREATE TABLE migration_failure_sentinel(value INTEGER) STRICT;\n"
                + "INSERT INTO deliberately_missing_table(value) VALUES (1);\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(AppLifecycleError, "Migration 2 failed"):
                register_and_install_builtin_apps(
                    app_store,
                    workspace_store,
                    start_path=repository,
                    now=upgraded_at,
                )

            sources = sorted(app_store.list_app_sources(), key=lambda source: source.version)
            self.assertEqual([source.version for source in sources], ["0.1.0", "0.2.0"])
            self.assertEqual(
                app_store.get_workspace_app_binding(
                    workspace_id="default",
                    app_id="video-studio",
                ),
                old_binding,
            )
            self.assertEqual((data_root / ".maverick-app.json").read_bytes(), marker_before_upgrade)
            self._assert_marker(data_root, app_version="0.1.0", schema_version="1")
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT value FROM app_metadata WHERE key = 'schema_version'"
                    ).fetchone()[0],
                    "1",
                )
                self.assertEqual(self._migration_history(connection), MIGRATION_HISTORY[:1])
                self.assertEqual(
                    connection.execute(
                        "SELECT name FROM projects WHERE project_id = 'project-before-failure'"
                    ).fetchone()[0],
                    "Still present",
                )
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_schema WHERE type = 'table'"
                    )
                }
                self.assertNotIn("project_projections", tables)
                self.assertNotIn("migration_failure_sentinel", tables)

    def _temporary_repository(self, root: Path) -> Path:
        (root / "AGENTS.md").write_text("test repository", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "maverick"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        (root / "apps").mkdir()
        (root / "workspaces" / "default").mkdir(parents=True)
        (root / "core").symlink_to(REPOSITORY_ROOT / "core", target_is_directory=True)
        shutil.copytree(
            APP_ROOT,
            root / "apps" / "video-studio",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules"),
        )
        return root

    def _make_schema_one_source(self, source_root: Path) -> None:
        contract_path = source_root / "app_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["version"] = "0.1.0"
        contract["storage"]["data_schema_version"] = "1"
        contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

        database_path = source_root / "backend" / "foundation" / "database.py"
        database_source = database_path.read_text(encoding="utf-8")
        database_source = database_source.replace(
            "LATEST_SCHEMA_VERSION = 3",
            "LATEST_SCHEMA_VERSION = 1",
        ).replace(
            """REVISION_ENGINE_TABLES = (
    "project_projections",
    "project_revision_navigation",
    "project_operation_batches",
    "project_autosaves",
    "project_outbox",
)""",
            "REVISION_ENGINE_TABLES: tuple[str, ...] = ()",
        )
        database_path.write_text(database_source, encoding="utf-8")

        service_path = source_root / "backend" / "foundation" / "service.py"
        service_path.write_text(
            service_path.read_text(encoding="utf-8").replace(
                'APP_VERSION = "0.2.0"',
                'APP_VERSION = "0.1.0"',
            ),
            encoding="utf-8",
        )
        (source_root / "migrations" / "0002_project_revision_engine.sql").unlink()
        (source_root / "migrations" / "0003_revision_integrity.sql").unlink()

    def _replace_with_current_source(self, source_root: Path) -> None:
        shutil.rmtree(source_root)
        shutil.copytree(
            APP_ROOT,
            source_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules"),
        )

    def _assert_marker(self, data_root: Path, *, app_version: str, schema_version: str) -> None:
        marker = json.loads((data_root / ".maverick-app.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["app_id"], "video-studio")
        self.assertEqual(marker["app_version"], app_version)
        self.assertEqual(marker["data_schema_version"], schema_version)

    def _migration_history(self, connection: sqlite3.Connection) -> list[tuple[int, str, str]]:
        return [
            (int(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            )
        ]


if __name__ == "__main__":
    unittest.main()
