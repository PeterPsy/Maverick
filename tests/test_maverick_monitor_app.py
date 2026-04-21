"""Tests for the Maverick Monitor app."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import run_json_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[1]
MONITOR_ROOT = REPO_ROOT / "apps" / "maverick-monitor"


class MaverickMonitorAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        source_apps_root = REPO_ROOT / "apps"
        for app_id in ("base-shell", "chat", "agents", "skills", "maverick-monitor"):
            shutil.copytree(
                source_apps_root / app_id,
                repo_root / "apps" / app_id,
                ignore=shutil.ignore_patterns("node_modules", "__pycache__"),
            )
        return repo_root

    def invoke(
        self,
        app,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
    ) -> tuple[int, dict | bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        raw = b"".join(app(environ, start_response))
        status = int(headers["__status__"].split()[0])
        if "application/json" in headers.get("Content-Type", ""):
            return status, json.loads(raw.decode("utf-8")), headers
        return status, raw, headers

    def run_backend(self, *, workspace_root: Path, data_root: Path, body: dict) -> dict:
        return run_json_entrypoint(
            MONITOR_ROOT / "backend" / "app_backend.py",
            payload={
                "workspace_root": str(workspace_root),
                "data_root": str(data_root),
                "body": body,
            },
            cwd=MONITOR_ROOT,
        )

    def test_contract_declares_monitor_surfaces(self) -> None:
        parsed = parse_app_contract_file(MONITOR_ROOT)

        self.assertEqual(parsed.app_id, "maverick-monitor")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["maverick-monitor"])
        self.assertEqual(parsed.contract.capabilities.mcp_tools, [])
        self.assertEqual(parsed.contract.storage.primary_paths, ["data/maverick-monitor/state.json"])

    def test_backend_snapshot_reports_machine_workspace_and_service_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo_root = Path(temp) / "maverick-v3"
            workspace_root = repo_root / "workspaces" / "default"
            data_root = workspace_root / "data" / "maverick-monitor"
            (repo_root / "apps" / "chat").mkdir(parents=True)
            (repo_root / "apps" / "chat" / "app_contract.json").write_text("{}", encoding="utf-8")
            (workspace_root / "storage" / "generated").mkdir(parents=True)
            (workspace_root / "storage" / "generated" / "report.md").write_text("# report", encoding="utf-8")

            result = self.run_backend(workspace_root=workspace_root, data_root=data_root, body={"action": "snapshot"})

            self.assertEqual(result["status_code"], 200)
            snapshot = result["json"]["snapshot"]
            self.assertEqual(snapshot["workspace_id"], "default")
            self.assertGreaterEqual(snapshot["machine"]["cpu_count"], 1)
            self.assertEqual(snapshot["service"]["installed_app_count"], 1)
            workspaces = {item["id"]: item for item in snapshot["workspaces"]}
            self.assertIn("default", workspaces)
            self.assertGreater(workspaces["default"]["generated_bytes"], 0)
            self.assertTrue((data_root / "state.json").is_file())

    def test_backend_updates_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace_root = Path(temp) / "maverick-v3" / "workspaces" / "default"
            data_root = workspace_root / "data" / "maverick-monitor"

            result = self.run_backend(
                workspace_root=workspace_root,
                data_root=data_root,
                body={"action": "settings.update", "selected_tab": "processes", "refresh_seconds": 2},
            )

            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["json"]["state"]["selected_tab"], "processes")
            self.assertEqual(result["json"]["state"]["refresh_seconds"], 5)

    def test_bootstrap_registers_installs_and_mounts_monitor(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        bindings = {binding.app_id: binding for binding in state.app_store.list_workspace_app_bindings("default")}
        status_frontend, body_frontend, _headers_frontend = self.invoke(app, path="/apps/maverick-monitor/")
        status_backend, body_backend, _headers_backend = self.invoke(
            app,
            path="/api/apps/maverick-monitor/backend",
            method="POST",
            body={"action": "health.check"},
        )

        self.assertIn("maverick-monitor", bindings)
        self.assertEqual(bindings["maverick-monitor"].status, "enabled")
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "maverick-monitor" / "state.json").is_file())
        self.assertEqual(status_frontend, 200)
        self.assertIn(b'id="root"', body_frontend)
        self.assertEqual(status_backend, 200)
        self.assertEqual(body_backend["status"], "ok")


if __name__ == "__main__":
    unittest.main()
