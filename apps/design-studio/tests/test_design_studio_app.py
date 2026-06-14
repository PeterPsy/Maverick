"""Tests for the Design Studio app."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]


class DesignStudioAppTests(unittest.TestCase):
    def test_contract_declares_sandbox_sidecar_and_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)

        self.assertEqual(parsed.app_id, "design-studio")
        self.assertEqual(parsed.contract.compatibility.supported_workspace_modes, ["sandbox"])
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.capabilities.skills, ["design-studio-ops"])
        sidecar = parsed.contract.services.http_sidecars[0]
        self.assertEqual(sidecar.service_id, "opendesign")
        self.assertEqual(sidecar.bind.host, "127.0.0.1")
        self.assertTrue(sidecar.proxy.streaming)
        self.assertTrue(sidecar.proxy.sse)
        self.assertFalse(sidecar.proxy.websocket)
        self.assertEqual(sidecar.proxy.route_policy.blocked[0].path_prefix, "/api/import/folder")

    def test_backend_creates_imports_and_exports_project(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "design-studio"
            uploaded = root / "storage" / "uploaded"
            generated = root / "storage" / "generated"
            source = uploaded / "brief.md"
            source.parent.mkdir(parents=True)
            generated.mkdir(parents=True)
            source.write_text("# Brief\n\nCreate a dashboard.\n", encoding="utf-8")

            created = self._run_entrypoint(
                APP_ROOT / "backend" / "app_backend.py",
                {
                    "surface": "backend",
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "uploaded_storage_root": str(uploaded),
                    "generated_storage_root": str(generated),
                    "body": {
                        "action": "create_project",
                        "arguments": {"name": "Dashboard", "prompt": "Operational metrics"},
                    },
                },
            )
            project_id = created["json"]["project"]["id"]

            imported = self._run_entrypoint(
                APP_ROOT / "backend" / "app_backend.py",
                {
                    "surface": "backend",
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "uploaded_storage_root": str(uploaded),
                    "generated_storage_root": str(generated),
                    "body": {
                        "action": "import_from_storage",
                        "arguments": {
                            "project_id": project_id,
                            "workspace_relative_path": "storage/uploaded/brief.md",
                        },
                    },
                },
            )
            exported = self._run_entrypoint(
                APP_ROOT / "backend" / "app_backend.py",
                {
                    "surface": "backend",
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "uploaded_storage_root": str(uploaded),
                    "generated_storage_root": str(generated),
                    "body": {
                        "action": "export_to_storage",
                        "arguments": {"project_id": project_id},
                    },
                },
            )

            self.assertEqual(imported["status_code"], 200)
            self.assertTrue((data_root / "imports" / project_id / "brief.md").is_file())
            self.assertEqual(exported["status_code"], 200)
            self.assertTrue((generated / "design-studio" / project_id / "manifest.json").is_file())
            self.assertTrue((generated / "design-studio" / project_id / "notes.md").is_file())

    def test_cli_and_mcp_state_entrypoints_return_ok(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data" / "design-studio"
            cli = self._run_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                {
                    "surface": "cli",
                    "command_id": "design-studio",
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "arguments": {"action": "state"},
                },
            )
            mcp = self._run_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                {
                    "surface": "mcp",
                    "tool_name": "design_studio_state",
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "arguments": {},
                },
            )

            self.assertTrue(cli["ok"])
            self.assertTrue(mcp["ok"])
            self.assertEqual(cli["state"]["schema_version"], "1")
            self.assertEqual(mcp["state"]["schema_version"], "1")

    def _run_entrypoint(self, entrypoint: Path, payload: dict) -> dict:
        process = subprocess.run(
            [sys.executable, str(entrypoint)],
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(APP_ROOT),
            env={"PYTHONPATH": str(REPO_ROOT)},
            text=True,
            check=True,
        )
        return json.loads(process.stdout or "{}")


if __name__ == "__main__":
    unittest.main()
