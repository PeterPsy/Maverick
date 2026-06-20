"""Phase 1 backend tests for Senses."""

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
from service import app_events_for_action, handle_action


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


def actor(user_id: str = "user-1", workspace_role: str = "member") -> dict[str, str | None]:
    return {
        "user_id": user_id,
        "workspace_role": workspace_role,
        "platform_role": "member",
        "effective_mode": "sandbox",
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


def start_and_complete_device(data_root: Path, user_id: str = "user-1") -> dict[str, object]:
    status, started = handle_action(
        data_root,
        {"action": "pairing.start", "_workspace_id": "default", "_app_actor": actor(user_id)},
    )
    if status != 201:
        raise AssertionError(started)
    status, completed = handle_action(
        data_root,
        {
            "action": "pairing.complete",
            "_workspace_id": "default",
            "_app_actor": actor(user_id),
            "code": started["pairing"]["code"],
            "device_display_name": "Marco iPhone",
            "device_kind": "ios",
            "platform": "ios",
            "client_device_id": "ios-client-1",
        },
    )
    if status != 200:
        raise AssertionError(completed)
    return completed


class SensesPhase1EntrypointTest(unittest.TestCase):
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
                table_names = {
                    row[0]
                    for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                }
            self.assertEqual(settings_count, 1)
            self.assertTrue(set(WORKSPACE_TABLES).issubset(table_names))

    def test_manifest_reports_phase_1_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, manifest = handle_action(
                Path(tmp),
                {
                    "action": "manifest",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "_app_dependencies": resolved_storage_dependencies(),
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(manifest["phase"], "phase-1")
            self.assertEqual(manifest["dependency_resolution"]["status"], "resolved")
            self.assertEqual(manifest["declared_surfaces"]["frontend"], True)
            self.assertIn("pairing.start", manifest["backend_actions"])
            self.assertIn("devices.revoke", manifest["backend_actions"])
            self.assertIn("ingest.frame", manifest["deferred_to_later_phases"])

    def test_missing_workspace_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "health"})
            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "missing_workspace_id")

    def test_pairing_start_and_complete_registers_device_without_raw_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, started = handle_action(
                data_root,
                {"action": "pairing.start", "_workspace_id": "default", "_app_actor": actor()},
            )
            self.assertEqual(status, 201)
            self.assertEqual(started["pairing"]["status"], "pending")
            self.assertRegex(started["pairing"]["code"], r"^[A-Z2-9]{8}$")
            self.assertEqual(started["pairing"]["qr_payload"]["backend_action"], "pairing.complete")

            status, completed = handle_action(
                data_root,
                {
                    "action": "pairing.complete",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "code": started["pairing"]["code"],
                    "device_display_name": "Marco iPhone",
                    "client_device_id": "client-123",
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(completed["device"]["status"], "active")
            self.assertEqual(completed["device"]["owner_user_id"], "user-1")
            self.assertEqual(completed["device_session"]["auth_mode"], "user_session_mvp")
            self.assertNotIn("device_token", json.dumps(completed))
            self.assertEqual(
                [event["resource"] for event in app_events_for_action("pairing.complete")],
                ["pairing", "devices"],
            )

    def test_pairing_complete_is_one_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, started = handle_action(
                data_root,
                {"action": "pairing.start", "_workspace_id": "default", "_app_actor": actor()},
            )
            self.assertEqual(status, 201)

            complete_payload = {
                "action": "pairing.complete",
                "_workspace_id": "default",
                "_app_actor": actor(),
                "code": started["pairing"]["code"],
                "device_display_name": "Marco iPhone",
            }
            status, first = handle_action(data_root, dict(complete_payload))
            self.assertEqual(status, 200)

            status, second = handle_action(data_root, dict(complete_payload))
            self.assertEqual(status, 404)
            self.assertEqual(second["error"], "invalid_or_expired_pairing_code")

            with sqlite3.connect(db_path(data_root)) as db:
                device_count = db.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
                session_count = db.execute("SELECT COUNT(*) FROM device_sessions").fetchone()[0]
                pairing = db.execute(
                    "SELECT status, device_id FROM pairing_sessions WHERE pairing_id = ?",
                    (started["pairing"]["pairing_id"],),
                ).fetchone()
            self.assertEqual(device_count, 1)
            self.assertEqual(session_count, 1)
            self.assertEqual(pairing, ("completed", first["device"]["device_id"]))

            status, listed = handle_action(
                data_root,
                {"action": "devices.list", "_workspace_id": "default", "_app_actor": actor()},
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(listed["devices"]), 1)
            self.assertEqual(listed["devices"][0]["display_name"], "Marco iPhone")

    def test_user_visibility_and_admin_include_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            start_and_complete_device(data_root, user_id="user-1")

            status, member_list = handle_action(
                data_root,
                {"action": "devices.list", "_workspace_id": "default", "_app_actor": actor("user-2")},
            )
            self.assertEqual(status, 200)
            self.assertEqual(member_list["devices"], [])

            status, admin_list = handle_action(
                data_root,
                {
                    "action": "devices.list",
                    "_workspace_id": "default",
                    "_app_actor": actor("admin-1", "admin"),
                    "include_all": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(admin_list["devices"]), 1)
            self.assertTrue(admin_list["devices"][0]["can_revoke"])

    def test_owner_can_revoke_device_and_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            completed = start_and_complete_device(data_root)
            device_id = completed["device"]["device_id"]

            status, revoked = handle_action(
                data_root,
                {
                    "action": "devices.revoke",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "device_id": device_id,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(revoked["device"]["status"], "revoked")

            with sqlite3.connect(db_path(data_root)) as db:
                session_status = db.execute(
                    "SELECT status FROM device_sessions WHERE device_id = ?",
                    (device_id,),
                ).fetchone()[0]
            self.assertEqual(session_status, "revoked")

    def test_settings_update_requires_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, denied = handle_action(
                data_root,
                {
                    "action": "settings.update",
                    "_workspace_id": "default",
                    "_app_actor": actor(),
                    "allow_member_pairing": False,
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(denied["error"], "senses_permission_forbidden")

            status, updated = handle_action(
                data_root,
                {
                    "action": "settings.update",
                    "_workspace_id": "default",
                    "_app_actor": actor("admin-1", "admin"),
                    "allow_member_pairing": False,
                    "pairing_code_ttl_seconds": 120,
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(updated["settings"]["allow_member_pairing"])
            self.assertEqual(updated["settings"]["pairing_code_ttl_seconds"], 120)

    def test_cli_and_mcp_expose_only_non_user_session_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cli_manifest = run_json_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "arguments": {"action": "manifest"},
                },
            )
            cli_overview = run_json_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "arguments": {"action": "overview"},
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
            mcp_pairing = run_json_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                cwd=APP_ROOT,
                payload={
                    "app_id": "senses",
                    "workspace_id": "default",
                    "data_root": tmp,
                    "app_dependencies": resolved_storage_dependencies(),
                    "tool_name": "senses_pairing_start",
                    "arguments": {},
                },
            )
            self.assertTrue(cli_manifest["ok"])
            self.assertEqual(cli_manifest["phase"], "phase-1")
            self.assertFalse(cli_overview["ok"])
            self.assertEqual(cli_overview["error"], "unsupported_cli_action")
            self.assertTrue(mcp_manifest["ok"])
            self.assertEqual(mcp_manifest["phase"], "phase-1")
            self.assertFalse(mcp_pairing["ok"])
            self.assertEqual(mcp_pairing["error"], "unsupported_tool")

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

    def test_reference_manifest_remains_capture_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_action(Path(tmp), {"action": "reference_manifest", "_workspace_id": "default"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["entity_types"], [])
            self.assertIn("capture", payload["notes"][0])


if __name__ == "__main__":
    unittest.main()
