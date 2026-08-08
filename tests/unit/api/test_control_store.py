"""Tests for control-plane persistence adapter selection."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.shared.json_file_collection import JsonFileCollection


class ControlStoreSettingsTestCase(unittest.TestCase):
    def test_default_control_store_uses_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            settings = ControlStoreSettings.from_environment(
                repository_root=repository_root,
                environment={},
            )
            collections = build_control_plane_collections(settings)

            self.assertEqual(settings.kind, "json")
            self.assertEqual(settings.json_root, repository_root / "data" / "control-plane" / "json")
            self.assertIsInstance(collections.workspace.workspaces, JsonFileCollection)
            self.assertIsInstance(collections.provider.definitions, JsonFileCollection)
            self.assertIsInstance(collections.provider.bindings, JsonFileCollection)
            self.assertIsInstance(collections.jobs.jobs, JsonFileCollection)
            self.assertEqual(collections.jobs.jobs.path, settings.json_root / "jobs" / "jobs.json")

    def test_mongo_uri_selects_mongo_when_kind_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = ControlStoreSettings.from_environment(
                repository_root=Path(temp_dir),
                environment={"MAVERICK_MONGODB_URI": "mongodb://127.0.0.1:27017/maverick"},
            )

            self.assertEqual(settings.kind, "mongo")
            self.assertEqual(settings.mongo_database, "maverick")

    def test_json_control_store_can_use_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_root = Path(temp_dir)
            settings = ControlStoreSettings.from_environment(
                repository_root=repository_root,
                environment={
                    "MAVERICK_CONTROL_STORE": "json",
                    "MAVERICK_JSON_CONTROL_STORE_ROOT": "control-db",
                },
            )
            collections = build_control_plane_collections(settings)

            self.assertEqual(settings.kind, "json")
            self.assertEqual(settings.json_root, repository_root / "control-db")
            self.assertIsInstance(collections.workspace.workspaces, JsonFileCollection)
            self.assertIsInstance(collections.provider.definitions, JsonFileCollection)
            self.assertIsInstance(collections.provider.bindings, JsonFileCollection)

    def test_mongo_settings_accept_legacy_uri_env_and_uri_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = ControlStoreSettings.from_environment(
                repository_root=Path(temp_dir),
                environment={
                    "MAVERICK_CONTROL_STORE": "mongodb",
                    "MAVERICK_MONGODB_URI": "mongodb://127.0.0.1:27017/maverick_from_uri",
                },
            )

            self.assertEqual(settings.kind, "mongo")
            self.assertEqual(settings.mongo_uri, "mongodb://127.0.0.1:27017/maverick_from_uri")
            self.assertEqual(settings.mongo_database, "maverick_from_uri")

    def test_explicit_mongo_database_overrides_uri_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = ControlStoreSettings.from_environment(
                repository_root=Path(temp_dir),
                environment={
                    "MAVERICK_CONTROL_STORE": "mongo",
                    "MAVERICK_MONGODB_URI": "mongodb://127.0.0.1:27017/ignored",
                    "MAVERICK_MONGODB_DATABASE": "configured",
                },
            )

            self.assertEqual(settings.mongo_database, "configured")

    def test_mongo_settings_accept_username_and_password_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = ControlStoreSettings.from_environment(
                repository_root=Path(temp_dir),
                environment={
                    "MAVERICK_CONTROL_STORE": "mongo",
                    "MAVERICK_MONGODB_URI": "mongodb://127.0.0.1:27017/maverick",
                    "MAVERICK_MONGODB_USERNAME": "maverick",
                    "MAVERICK_MONGODB_PASSWORD_REF": "platform:secret-alias/mongodb-password",
                },
            )

            self.assertEqual(settings.kind, "mongo")
            self.assertEqual(settings.mongo_username, "maverick")
            self.assertEqual(settings.mongo_password_ref, "platform:secret-alias/mongodb-password")
            self.assertNotIn("@", settings.mongo_uri or "")

    def test_unknown_control_store_kind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "Unsupported MAVERICK_CONTROL_STORE"):
                ControlStoreSettings.from_environment(
                    repository_root=Path(temp_dir),
                    environment={"MAVERICK_CONTROL_STORE": "postgres"},
                )


if __name__ == "__main__":
    unittest.main()
