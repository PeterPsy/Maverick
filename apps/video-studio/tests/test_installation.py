"""Generic installation-level registration and binding test."""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from core.apps.errors import WorkspaceAppBindingNotFoundError
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.store import AppCollections, AppDocumentStore
from tests.support.collections import FakeCollection


APP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = APP_ROOT.parents[1]


def _store() -> AppDocumentStore:
    return AppDocumentStore(
        AppCollections(
            app_sources=FakeCollection(),
            workspace_local_app_projects=FakeCollection(),
            workspace_app_bindings=FakeCollection(),
            workspace_app_dependency_selections=FakeCollection(),
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
            self.assertEqual(marker["data_schema_version"], "2")
            with closing(sqlite3.connect(data_root / "app.db")) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                    2,
                )

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


if __name__ == "__main__":
    unittest.main()
