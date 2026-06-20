"""Phase 0 backend tests for Senses."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

MAVERICK_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "core").is_dir())
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAVERICK_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from database import WORKSPACE_TABLES, db_path, ensure_schema, table_columns
from service import handle_action


class SensesPhase0EntrypointTest(unittest.TestCase):
    def test_schema_is_workspace_scoped_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            ensure_schema(data_root, "default")
            ensure_schema(data_root, "default")
            self.assertTrue(db_path(data_root).is_file())
            for table in WORKSPACE_TABLES:
                self.assertIn("workspace_id", table_columns(data_root, table))
            with sqlite3.connect(db_path(data_root)) as db:
                settings_count = db.execute(
                    "SELECT COUNT(*) FROM settings WHERE workspace_id = ?",
                    ("default",),
                ).fetchone()[0]
            self.assertEqual(settings_count, 1)

    def test_manifest_reports_required_storage_dependencies(self) -> None:
        dependencies = {
            "workspace_id": "default",
            "consumer_app_id": "senses",
            "status": "resolved",
            "dependencies": [
                {
                    "alias": "storage-file-content-write",
                    "interface": "file.content.write",
                    "version": "^1",
                    "required": True,
                    "cardinality": "one",
                    "status": "resolved",
                    "selected_provider_app_ids": ["storage"],
                    "candidates": [{"app_id": "storage"}],
                    "blocked_reason": None,
                },
                {
                    "alias": "storage-file-catalog",
                    "interface": "file.catalog",
                    "version": "^1",
                    "required": True,
                    "cardinality": "one",
                    "status": "resolved",
                    "selected_provider_app_ids": ["storage"],
                    "candidates": [{"app_id": "storage"}],
                    "blocked_reason": None,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            status, manifest = handle_action(
                Path(tmp),
                {"action": "manifest", "_workspace_id": "default", "_app_dependencies": dependencies},
            )
            self.assertEqual(status, 200)
            self.assertEqual(manifest["dependency_resolution"]["status"], "resolved")
            self.assertEqual(manifest["declared_surfaces"]["frontend"], False)
            self.assertIn("ingest.frame", manifest["deferred_to_later_phases"])

    def test_health_documents_missing_dependency_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, health = handle_action(Path(tmp), {"action": "health", "_workspace_id": "default"})
            self.assertEqual(status, 200)
            self.assertEqual(health["dependencies"]["status"], "unknown")
            self.assertEqual(
                health["dependencies"]["blocked_reason"],
                "dependency_resolution_not_provided_by_host",
            )

    def test_reference_manifest_is_empty_until_records_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "reference_manifest"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["entity_types"], [])


if __name__ == "__main__":
    unittest.main()
