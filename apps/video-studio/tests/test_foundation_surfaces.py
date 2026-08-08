"""Lifecycle and executable-surface parity tests for Video Studio foundation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


APP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = APP_ROOT.parents[1]


def _invoke(relative_path: str, payload: dict[str, object]) -> dict[str, object]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(REPOSITORY_ROOT)
        if not existing
        else f"{REPOSITORY_ROOT}{os.pathsep}{existing}"
    )
    result = subprocess.run(
        [sys.executable, str(APP_ROOT / relative_path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=APP_ROOT,
        timeout=20,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    decoded = json.loads(result.stdout)
    if not isinstance(decoded, dict):
        raise AssertionError("Entrypoint did not return a JSON object.")
    return decoded


class FoundationSurfacesTest(unittest.TestCase):
    def test_lifecycle_hooks_are_idempotent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = str(Path(temp_dir) / "data" / "video-studio")
            payload = {
                "app_id": "video-studio",
                "workspace_id": "default",
                "data_root": data_root,
            }

            first = _invoke("hooks/install.py", payload)
            second = _invoke("hooks/install.py", payload)
            migrated = _invoke("hooks/migrate.py", payload)
            health = _invoke("hooks/health_check.py", payload)

            self.assertEqual(first["applied_migrations"], [1])
            self.assertEqual(second["applied_migrations"], [])
            self.assertEqual(migrated["applied_migrations"], [])
            self.assertTrue(health["ok"])
            self.assertEqual(health["status"], "healthy")

    def test_backend_cli_and_mcp_share_foundation_results(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = str(Path(temp_dir) / "data" / "video-studio")
            base = {
                "app_id": "video-studio",
                "workspace_id": "default",
                "data_root": data_root,
            }
            _invoke("hooks/install.py", base)

            backend = _invoke(
                "backend/app_backend.py",
                {**base, "body": {"action": "schema"}},
            )
            cli = _invoke(
                "cli/app_cli.py",
                {
                    **base,
                    "command_id": "video-studio.video-studio",
                    "arguments": {"action": "schema"},
                },
            )
            mcp = _invoke(
                "mcp/server.py",
                {
                    **base,
                    "tool_name": "video_studio_foundation",
                    "arguments": {"action": "schema"},
                },
            )
            backend_json = backend["json"]
            assert isinstance(backend_json, dict)
            for key in (
                "schema_version",
                "metadata_schema_version",
                "latest_schema_version",
                "journal_mode",
                "table_count",
                "domain_aggregate_count",
                "tables",
                "migrations",
            ):
                self.assertEqual(backend_json[key], cli[key], key)
                self.assertEqual(cli[key], mcp[key], key)
            self.assertEqual(backend["status_code"], 200)
            self.assertEqual(cli["status_code"], 200)
            self.assertEqual(mcp["status_code"], 200)
            combined = json.dumps([backend, cli, mcp])
            self.assertNotIn(data_root, combined)

    def test_capability_manifest_does_not_claim_video_domain_features(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = str(Path(temp_dir) / "data")
            base = {
                "app_id": "video-studio",
                "workspace_id": "default",
                "data_root": data_root,
            }
            _invoke("hooks/install.py", base)
            cli = _invoke(
                "cli/app_cli.py",
                {
                    **base,
                    "command_id": "video-studio.video-studio",
                    "arguments": {"action": "capabilities"},
                },
            )
            reference_manifest = _invoke(
                "mcp/server.py",
                {
                    **base,
                    "tool_name": "video_studio_reference_manifest",
                    "arguments": {},
                },
            )
            self.assertEqual(cli["domain_capabilities"], [])
            self.assertEqual(
                cli["actions"],
                ["status", "schema", "health", "capabilities"],
            )
            self.assertEqual(reference_manifest["entity_types"], [])

    def test_backend_errors_are_typed_and_do_not_leak_paths(self) -> None:
        unavailable = _invoke(
            "backend/app_backend.py",
            {
                "app_id": "video-studio",
                "workspace_id": "default",
                "data_root": "",
                "body": {"action": "status"},
            },
        )
        unsupported = _invoke(
            "backend/app_backend.py",
            {
                "app_id": "video-studio",
                "workspace_id": "default",
                "data_root": "",
                "body": {"action": "render"},
            },
        )

        self.assertEqual(unavailable["status_code"], 503)
        self.assertEqual(unavailable["json"]["error"]["code"], "foundation_unavailable")
        self.assertEqual(unsupported["status_code"], 400)
        self.assertEqual(unsupported["json"]["error"]["code"], "unsupported_action")

        with TemporaryDirectory() as temp_dir:
            absent_root = Path(temp_dir) / "must-not-be-created"
            missing = _invoke(
                "backend/app_backend.py",
                {
                    "app_id": "video-studio",
                    "workspace_id": "default",
                    "data_root": str(absent_root),
                    "body": {"action": "status"},
                },
            )
            self.assertEqual(missing["status_code"], 503)
            self.assertFalse(absent_root.exists())

    def test_sidecar_requires_token_and_serves_only_read_routes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = str(Path(temp_dir) / "data")
            base = {
                "app_id": "video-studio",
                "workspace_id": "default",
                "data_root": data_root,
            }
            _invoke("hooks/install.py", base)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
            token = "test-technical-token"
            env = dict(os.environ)
            env.update(
                {
                    "VIDEO_STUDIO_DATA_ROOT": data_root,
                    "VIDEO_STUDIO_SIDECAR_HOST": "127.0.0.1",
                    "VIDEO_STUDIO_SIDECAR_PORT": str(port),
                    "VIDEO_STUDIO_SIDECAR_TOKEN": token,
                }
            )
            process = subprocess.Popen(
                [sys.executable, str(APP_ROOT / "backend" / "sidecar_server.py")],
                cwd=APP_ROOT / "backend",
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                payload = self._wait_for_sidecar(port, token, process)
                self.assertEqual(payload["status"], "healthy")
                self.assertEqual(payload["surface"], "sidecar")
                self.assertNotIn(data_root, json.dumps(payload))
                with self.assertRaises(HTTPError) as unauthorized:
                    urlopen(f"http://127.0.0.1:{port}/status", timeout=2)
                self.assertEqual(unauthorized.exception.code, 401)
                missing = Request(
                    f"http://127.0.0.1:{port}/projects",
                    headers={"Authorization": f"Bearer {token}"},
                )
                with self.assertRaises(HTTPError) as not_found:
                    urlopen(missing, timeout=2)
                self.assertEqual(not_found.exception.code, 404)
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=3)

    def _wait_for_sidecar(
        self,
        port: int,
        token: str,
        process: subprocess.Popen[str],
    ) -> dict[str, object]:
        request = Request(
            f"http://127.0.0.1:{port}/health",
            headers={"Authorization": f"Bearer {token}"},
        )
        deadline = time.monotonic() + 5
        last_error = "sidecar did not start"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr is not None else ""
                self.fail(stderr or "sidecar exited before health")
            try:
                with urlopen(request, timeout=1) as response:
                    return json.loads(response.read().decode("utf-8"))
            except OSError as error:
                last_error = str(error)
                time.sleep(0.05)
        self.fail(last_error)


if __name__ == "__main__":
    unittest.main()
