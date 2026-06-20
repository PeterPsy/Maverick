"""Phase 0 backend tests for Senses."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

MAVERICK_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "core").is_dir())
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAVERICK_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from core.shared.entrypoints import run_json_entrypoint
from database import WORKSPACE_TABLES, db_path, ensure_schema, table_columns
from service import handle_action


def resolved_storage_dependencies() -> dict[str, object]:
    return {
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


def run_hook(relative_path: str, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(MAVERICK_ROOT)
        if not env.get("PYTHONPATH")
        else f"{MAVERICK_ROOT}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, relative_path],
        cwd=APP_ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


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
        with tempfile.TemporaryDirectory() as tmp:
            status, manifest = handle_action(
                Path(tmp),
                {"action": "manifest", "_workspace_id": "default", "_app_dependencies": resolved_storage_dependencies()},
            )
            self.assertEqual(status, 200)
            self.assertEqual(manifest["dependency_resolution"]["status"], "resolved")
            self.assertEqual(manifest["declared_surfaces"]["frontend"], False)
            self.assertIn("ingest.frame", manifest["deferred_to_later_phases"])

    def test_missing_workspace_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "health"})
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "missing_workspace_id")

    def test_cli_and_mcp_use_host_dependency_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cli_health = run_json_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "arguments": {"action": "health"},
                },
            )
            mcp_manifest = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "tool_name": "senses_operations_manifest",
                    "arguments": {},
                },
            )
            self.assertTrue(cli_health["ok"])
            self.assertEqual(cli_health["dependencies"]["status"], "resolved")
            self.assertEqual(mcp_manifest["dependency_resolution"]["status"], "resolved")

    def test_mcp_rejects_unknown_tool_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "tool_name": "senses_unknown",
                    "arguments": {},
                },
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "unsupported_tool")

    def test_health_documents_missing_dependency_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, health = handle_action(Path(tmp), {"action": "health", "_workspace_id": "default"})
            self.assertEqual(status, 200)
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "dependency_resolution_pending")
            self.assertEqual(health["storage"]["database"]["primary_path"], "data/senses/senses.sqlite")
            self.assertNotIn("path", health["storage"]["database"])
            self.assertEqual(health["dependencies"]["status"], "unknown")
            self.assertEqual(
                health["dependencies"]["blocked_reason"],
                "dependency_resolution_not_provided_by_host",
            )

    def test_health_hook_fails_probe_when_dependencies_are_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_hook(
                "hooks/health_check.py",
                {
                    "workspace_id": "default",
                    "app_id": "senses",
                    "data_root": tmp,
                    "hook_name": "health_check",
                },
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "dependency_resolution_pending")
            self.assertEqual(payload["dependencies"]["status"], "unknown")

    def test_health_hook_allows_install_sequence_without_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_hook(
                "hooks/health_check.py",
                {
                    "workspace_id": "default",
                    "app_id": "senses",
                    "data_root": tmp,
                    "hook_name": "install",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertNotIn("dependencies", payload)

    def test_reference_manifest_is_empty_until_records_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "reference_manifest", "_workspace_id": "default"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["entity_types"], [])


if __name__ == "__main__":
    unittest.main()
