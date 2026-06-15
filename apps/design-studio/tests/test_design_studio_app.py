"""Tests for the Design Studio app."""

from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
import unittest
from urllib.error import URLError
from urllib.request import Request, urlopen

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.dependencies import save_app_dependency_selection
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import EntrypointShutdownController


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
        self.assertEqual(sidecar.package_manager, "corepack/pnpm")
        self.assertEqual(sidecar.command, ["python3", "opendesign_launcher.py"])
        self.assertEqual(sidecar.env.get("MAVERICK_OPENDESIGN_ALLOW_FALLBACK"), "0")
        self.assertEqual(sidecar.bind.host, "127.0.0.1")
        self.assertTrue(sidecar.proxy.streaming)
        self.assertTrue(sidecar.proxy.sse)
        self.assertFalse(sidecar.proxy.websocket)
        pass_through = [rule.path_prefix for rule in sidecar.proxy.route_policy.pass_through]
        blocked = [rule.path_prefix for rule in sidecar.proxy.route_policy.blocked]
        handled_by_core = [rule.path_prefix for rule in sidecar.proxy.route_policy.handled_by_core]
        self.assertIn("/index.html", pass_through)
        self.assertNotIn("/", pass_through)
        self.assertIn("/api/dialog/open-folder", blocked)
        self.assertIn("/api/media/config", handled_by_core)
        self.assertIn("/api/projects", handled_by_core)

    def test_opendesign_bundle_manifest_matches_contract_policy(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        sidecar = parsed.contract.services.http_sidecars[0]
        manifest = json.loads((APP_ROOT / "service" / "opendesign_bundle.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["upstream"]["commit"], "eb245799adf07e7727ad5f970485d809bad5780e")
        self.assertEqual(manifest["bundle"]["daemon_package"], "@open-design/daemon")
        self.assertIn("apps/daemon", manifest["include_paths"])
        self.assertIn("apps/web", manifest["include_paths"])
        self.assertIn("apps/desktop", manifest["exclude_paths"])
        self.assertEqual(
            [rule["path_prefix"] for rule in manifest["sandbox"]["pass_through"]],
            [rule.path_prefix for rule in sidecar.proxy.route_policy.pass_through],
        )
        self.assertEqual(
            [rule["path_prefix"] for rule in manifest["sandbox"]["blocked"]],
            [rule.path_prefix for rule in sidecar.proxy.route_policy.blocked],
        )
        self.assertEqual(
            [rule["path_prefix"] for rule in manifest["sandbox"]["handled_by_core"]],
            [rule.path_prefix for rule in sidecar.proxy.route_policy.handled_by_core],
        )

    def test_opendesign_launcher_uses_fallback_only_when_bundle_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "opendesign"
            port = self._free_port()
            token = "launcher-test-token"
            env = {
                **os.environ,
                "PYTHONPATH": str(REPO_ROOT),
                "OD_BIND_HOST": "127.0.0.1",
                "OD_PORT": str(port),
                "OD_DATA_DIR": str(data_dir),
                "OD_MEDIA_CONFIG_DIR": str(data_dir / "media-config"),
                "OD_API_TOKEN": token,
                "OD_SANDBOX_MODE": "1",
                "MAVERICK_OPENDESIGN_BUNDLE_DIR": str(root / "missing-open-design"),
                "MAVERICK_OPENDESIGN_ALLOW_EXTERNAL_BUNDLE": "1",
                "MAVERICK_OPENDESIGN_ALLOW_FALLBACK": "1",
            }
            process = subprocess.Popen(
                [sys.executable, str(APP_ROOT / "service" / "opendesign_launcher.py")],
                cwd=str(APP_ROOT / "service"),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(self._stop_process, process)
            payload = self._wait_for_json(
                f"http://127.0.0.1:{port}/api/version",
                headers={"Authorization": f"Bearer {token}"},
                process=process,
            )

            self.assertEqual(payload["mode"], "maverick-compatibility-fallback")
            self.assertFalse(payload["bundle_configured"])
            self.assertTrue(payload["technical_token_seen"])
            status_path = data_dir / "launcher-status.json"
            self.assertTrue(status_path.is_file())
            status_text = status_path.read_text(encoding="utf-8")
            self.assertIn("compatibility-fallback", status_text)
            self.assertNotIn(token, status_text)
            self.assertNotIn(str(root), status_text)

    def test_opendesign_launcher_fails_closed_without_bundle_by_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "opendesign"
            env = {
                **os.environ,
                "PYTHONPATH": str(REPO_ROOT),
                "OD_BIND_HOST": "127.0.0.1",
                "OD_PORT": str(self._free_port()),
                "OD_DATA_DIR": str(data_dir),
                "OD_MEDIA_CONFIG_DIR": str(data_dir / "media-config"),
                "OD_API_TOKEN": "launcher-test-token",
                "OD_SANDBOX_MODE": "1",
                "MAVERICK_OPENDESIGN_BUNDLE_DIR": str(root / "missing-open-design"),
                "MAVERICK_OPENDESIGN_ALLOW_EXTERNAL_BUNDLE": "1",
                "MAVERICK_OPENDESIGN_ALLOW_FALLBACK": "0",
            }

            process = subprocess.run(
                [sys.executable, str(APP_ROOT / "service" / "opendesign_launcher.py")],
                cwd=str(APP_ROOT / "service"),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertNotEqual(process.returncode, 0)
            self.assertIn("Curated OpenDesign daemon unavailable", process.stderr)
            self.assertFalse((data_dir / "launcher-status.json").exists())

    def test_backend_creates_imports_and_requests_storage_export_writes(self) -> None:
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
            import_record = imported["json"]["import"]
            self.assertEqual(import_record["status"], "imported")
            self.assertTrue((data_root / import_record["app_data_path"]).is_file())
            self.assertEqual(exported["status_code"], 200)
            export_record = exported["json"]["export"]
            export_id = export_record["export_id"]
            requests = exported["json"]["dependency_backend_requests"]
            self.assertEqual(export_record["status"], "pending")
            self.assertEqual([request["dependency_alias"] for request in requests], ["storage-write", "storage-write"])
            self.assertEqual(
                [request["body"]["workspace_relative_path"] for request in requests],
                [
                    f"storage/generated/design-studio/{project_id}/{export_id}/manifest.json",
                    f"storage/generated/design-studio/{project_id}/{export_id}/notes.md",
                ],
            )
            self.assertFalse((generated / "design-studio" / project_id / export_id / "manifest.json").exists())

            for request in requests:
                callback_payload = request["callback"]["payload"]
                self._run_entrypoint(
                    APP_ROOT / "backend" / "app_backend.py",
                    {
                        "surface": "dependency_backend_request_callback",
                        "app_id": "design-studio",
                        "workspace_id": "default",
                        "data_root": str(data_root),
                        "uploaded_storage_root": str(uploaded),
                        "generated_storage_root": str(generated),
                        "body": {
                            **callback_payload,
                            "action": "record_storage_export_result",
                            "dependency_backend_status": "completed",
                            "dependency_backend_result": {
                                "status_code": 200,
                                "json": {
                                    "file": {
                                        "workspace_relative_path": callback_payload["workspace_relative_path"],
                                    }
                                },
                            },
                        },
                    },
                )

            state = self._run_entrypoint(
                APP_ROOT / "backend" / "app_backend.py",
                {
                    "surface": "backend",
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "uploaded_storage_root": str(uploaded),
                    "generated_storage_root": str(generated),
                    "body": {"action": "state"},
                },
            )
            final_export = state["json"]["state"]["projects"][0]["exports"][0]
            self.assertEqual(final_export["status"], "exported")
            self.assertEqual(
                final_export["completed_workspace_relative_paths"],
                export_record["workspace_relative_paths"],
            )

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

    def test_hosted_backend_imports_and_exports_through_storage_dependencies(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self._test_platform_env():
                repo_root = self._temporary_repo_root(Path(temp_dir))
                state = bootstrap_platform_state(start_path=repo_root)
                with self._repo_pythonpath():
                    self._install_platform_app(state, repo_root, "storage")
                    self._install_platform_app(state, repo_root, "design-studio")
                save_app_dependency_selection(
                    state.app_store,
                    workspace_id="default",
                    consumer_app_id="design-studio",
                    alias="storage-read",
                    provider_app_ids=["storage"],
                    workspace_store=state.workspace_store,
                    start_path=repo_root,
                )
                save_app_dependency_selection(
                    state.app_store,
                    workspace_id="default",
                    consumer_app_id="design-studio",
                    alias="storage-write",
                    provider_app_ids=["storage"],
                    workspace_store=state.workspace_store,
                    start_path=repo_root,
                )
                shutdown = EntrypointShutdownController()
                self.addCleanup(shutdown.begin_shutdown)
                app = PlatformHost(state, start_path=repo_root, shutdown_controller=shutdown)
                cookie = self._login(app)

            with self._repo_pythonpath():
                uploaded_root = repo_root / "workspaces" / "default" / "storage" / "uploaded"
                uploaded_root.mkdir(parents=True, exist_ok=True)
                (uploaded_root / "brief.md").write_text("# Brief\n\nCreate a dashboard.\n", encoding="utf-8")
                created_status, created_body, _headers = self._invoke_backend(
                    app,
                    cookie=cookie,
                    body={
                        "action": "create_project",
                        "arguments": {"name": "Dashboard", "prompt": "Operational metrics"},
                    },
                )
                self.assertEqual(created_status, 200)
                project_id = json.loads(created_body.decode("utf-8"))["project"]["id"]
                import_status, import_body, _import_headers = self._invoke_backend(
                    app,
                    cookie=cookie,
                    body={
                        "action": "import_from_storage",
                        "arguments": {
                            "project_id": project_id,
                            "workspace_relative_path": "storage/uploaded/brief.md",
                        },
                    },
                )
                import_payload = json.loads(import_body.decode("utf-8"))
                self.assertEqual(import_status, 200)
                self.assertEqual(
                    [item["status"] for item in import_payload["dependency_backend_request_results"]],
                    ["completed"],
                )

                export_status, export_body, _export_headers = self._invoke_backend(
                    app,
                    cookie=cookie,
                    body={"action": "export_to_storage", "arguments": {"project_id": project_id}},
                )

                export_payload = json.loads(export_body.decode("utf-8"))
                export_record = export_payload["export"]
                export_id = export_record["export_id"]
                generated_root = repo_root / "workspaces" / "default" / "storage" / "generated"
                export_root = generated_root / "design-studio" / project_id / export_id

                self.assertEqual(export_status, 200)
                self.assertTrue((export_root / "manifest.json").is_file())
                self.assertTrue((export_root / "notes.md").is_file())
                self.assertEqual(
                    [item["status"] for item in export_payload["dependency_backend_request_results"]],
                    ["completed", "completed"],
                )

                state_status, state_body, _state_headers = self._invoke_backend(
                    app,
                    cookie=cookie,
                    body={"action": "state"},
                )
            state_payload = json.loads(state_body.decode("utf-8"))
            final_import = state_payload["state"]["projects"][0]["imports"][0]
            final_export = state_payload["state"]["projects"][0]["exports"][0]
            self.assertEqual(state_status, 200)
            self.assertEqual(final_import["status"], "imported")
            self.assertEqual(final_import["workspace_relative_path"], "storage/uploaded/brief.md")
            imported_app_path = (
                repo_root
                / "workspaces"
                / "default"
                / "data"
                / "design-studio"
                / final_import["app_data_path"]
            )
            self.assertTrue(imported_app_path.is_file())
            self.assertEqual(final_export["status"], "exported")
            self.assertEqual(final_export["completed_workspace_relative_paths"], export_record["workspace_relative_paths"])

    def test_sidecar_core_routes_handle_provider_and_storage_without_passing_to_sidecar(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self._test_platform_env():
                repo_root = self._temporary_repo_root(Path(temp_dir))
                state = bootstrap_platform_state(start_path=repo_root)
                with self._repo_pythonpath():
                    self._install_platform_app(state, repo_root, "storage")
                    self._install_platform_app(state, repo_root, "design-studio")
                save_app_dependency_selection(
                    state.app_store,
                    workspace_id="default",
                    consumer_app_id="design-studio",
                    alias="storage-read",
                    provider_app_ids=["storage"],
                    workspace_store=state.workspace_store,
                    start_path=repo_root,
                )
                save_app_dependency_selection(
                    state.app_store,
                    workspace_id="default",
                    consumer_app_id="design-studio",
                    alias="storage-write",
                    provider_app_ids=["storage"],
                    workspace_store=state.workspace_store,
                    start_path=repo_root,
                )
                shutdown = EntrypointShutdownController()
                self.addCleanup(shutdown.begin_shutdown)
                app = PlatformHost(state, start_path=repo_root, shutdown_controller=shutdown)
                cookie = self._login(app)

            with self._repo_pythonpath():
                uploaded_root = repo_root / "workspaces" / "default" / "storage" / "uploaded"
                uploaded_root.mkdir(parents=True, exist_ok=True)
                (uploaded_root / "brief.md").write_text("# Brief\n\nCreate a dashboard.\n", encoding="utf-8")
                created_status, created_body, _headers = self._invoke_backend(
                    app,
                    cookie=cookie,
                    body={
                        "action": "create_project",
                        "arguments": {"name": "Dashboard", "prompt": "Operational metrics"},
                    },
                )
                self.assertEqual(created_status, 200)
                project_id = json.loads(created_body.decode("utf-8"))["project"]["id"]

                media_status, media_body, _media_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/media/config",
                    cookie=cookie,
                )
                provider_status, provider_body, _provider_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/provider/chat",
                    method="POST",
                    body={"apiKey": "provider-fixture-token", "prompt": "dashboard"},
                    cookie=cookie,
                )
                import_status, import_body, _import_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/import/storage",
                    method="POST",
                    body={
                        "project_id": project_id,
                        "workspace_relative_path": "storage/uploaded/brief.md",
                    },
                    cookie=cookie,
                )
                export_status, export_body, _export_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/export/storage",
                    method="POST",
                    body={"project_id": project_id},
                    cookie=cookie,
                )
                projects_status, projects_body, _projects_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/projects",
                    cookie=cookie,
                )
                terminal_status, terminal_body, _terminal_headers = self._invoke(
                    app,
                    path=f"/api/apps/design-studio/sidecars/opendesign/api/projects/{project_id}/terminals",
                    cookie=cookie,
                )
                state_status, state_body, _state_headers = self._invoke_backend(
                    app,
                    cookie=cookie,
                    body={"action": "state"},
                )

            media_payload = json.loads(media_body.decode("utf-8"))
            provider_payload = json.loads(provider_body.decode("utf-8"))
            import_payload = json.loads(import_body.decode("utf-8"))
            export_payload = json.loads(export_body.decode("utf-8"))
            projects_payload = json.loads(projects_body.decode("utf-8"))
            terminal_payload = json.loads(terminal_body.decode("utf-8"))
            state_payload = json.loads(state_body.decode("utf-8"))
            media_config_root = repo_root / "workspaces" / "default" / "data" / "design-studio" / "opendesign" / "media-config"
            media_config_text = "\n".join(path.read_text(encoding="utf-8") for path in media_config_root.glob("*") if path.is_file())
            export_record = export_payload["export"]
            export_id = export_record["export_id"]
            export_root = repo_root / "workspaces" / "default" / "storage" / "generated" / "design-studio" / project_id / export_id
            final_project = state_payload["state"]["projects"][0]
            final_import = final_project["imports"][0]
            final_export = final_project["exports"][0]

            self.assertEqual(media_status, 200)
            self.assertFalse(media_payload["sidecar_reached"])
            self.assertFalse(media_payload["secrets_persisted"])
            self.assertEqual(provider_status, 503)
            self.assertEqual(provider_payload["error"], "provider_proxy_not_configured")
            self.assertFalse(provider_payload["sidecar_reached"])
            self.assertNotIn("provider-fixture-token", media_config_text)
            self.assertEqual(import_status, 200)
            self.assertEqual(
                [item["status"] for item in import_payload["dependency_backend_request_results"]],
                ["completed"],
            )
            self.assertEqual(export_status, 200)
            self.assertTrue((export_root / "manifest.json").is_file())
            self.assertTrue((export_root / "notes.md").is_file())
            self.assertEqual(
                [item["status"] for item in export_payload["dependency_backend_request_results"]],
                ["completed", "completed"],
            )
            self.assertEqual(projects_status, 200)
            self.assertEqual(projects_payload["projects"][0]["id"], project_id)
            self.assertEqual(terminal_status, 404)
            self.assertEqual(terminal_payload["error"], "opendesign_project_route_not_available")
            self.assertEqual(state_status, 200)
            self.assertEqual(final_import["status"], "imported")
            self.assertEqual(final_export["status"], "exported")

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

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_for_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        process: subprocess.Popen[str],
    ) -> dict:
        last_error = ""
        for _attempt in range(50):
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                self.fail(f"OpenDesign launcher exited early: stdout={stdout!r} stderr={stderr!r}")
            try:
                with urlopen(Request(url, headers=headers), timeout=0.2) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (OSError, URLError) as error:
                last_error = str(error)
                time.sleep(0.1)
        self.fail(f"OpenDesign launcher did not become ready: {last_error}")

    def _stop_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            process.communicate(timeout=1)
            return
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)

    def _temporary_repo_root(self, root: Path) -> Path:
        repo_root = root / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _install_platform_app(self, state, repo_root: Path, app_id: str) -> None:
        self._copy_app_source(repo_root, app_id)
        source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(repo_root / "apps" / app_id),
        )
        install_store_app(
            state.app_store,
            source_id=source.source_id,
            workspace_id="default",
            start_path=repo_root,
            observability_store=state.observability_store,
        )

    def _copy_app_source(self, repo_root: Path, app_id: str) -> None:
        target = repo_root / "apps" / app_id
        if target.exists():
            return
        shutil.copytree(
            REPO_ROOT / "apps" / app_id,
            target,
            ignore=shutil.ignore_patterns("node_modules", "__pycache__", "*.pyc", ".pytest_cache"),
        )

    @contextmanager
    def _repo_pythonpath(self):
        previous = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = str(REPO_ROOT) if not previous else f"{REPO_ROOT}{os.pathsep}{previous}"
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = previous

    @contextmanager
    def _test_platform_env(self):
        keys = ("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS", "MAVERICK_ADMIN_USERNAME", "MAVERICK_ADMIN_PASSWORD")
        previous = {key: os.environ.get(key) for key in keys}
        os.environ["MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS"] = "1"
        os.environ["MAVERICK_ADMIN_USERNAME"] = "admin"
        os.environ["MAVERICK_ADMIN_PASSWORD"] = "maverick"
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def _login(self, app: PlatformHost) -> str:
        status, _body, headers = self._invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "admin", "password": "maverick"},
        )
        self.assertEqual(status, 200, _body.decode("utf-8"))
        return headers["Set-Cookie"].split(";", 1)[0]

    def _invoke_backend(self, app: PlatformHost, *, cookie: str, body: dict) -> tuple[int, bytes, dict[str, str]]:
        return self._invoke(
            app,
            path="/api/apps/design-studio/backend",
            method="POST",
            body=body,
            cookie=cookie,
        )

    def _invoke(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
            "HTTP_HOST": "testserver",
            "SERVER_NAME": "testserver",
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie
            environ["HTTP_ORIGIN"] = "http://testserver"

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        result = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), result, headers


if __name__ == "__main__":
    unittest.main()
