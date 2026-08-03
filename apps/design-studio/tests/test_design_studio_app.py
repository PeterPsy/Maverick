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
from tempfile import TemporaryDirectory
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.dependencies import save_app_dependency_selection
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.contracts import parse_app_contract_file
from core.providers.service import configure_workspace_provider
from core.shared.entrypoints import EntrypointShutdownController


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
FIXTURES_ROOT = APP_ROOT / "tests" / "fixtures"


class DesignStudioAppTests(unittest.TestCase):
    def test_wp0_pinned_route_and_supply_chain_inventories_are_complete(self) -> None:
        routes = json.loads(
            (APP_ROOT / "service" / "opendesign_routes_0_16_1.json").read_text(encoding="utf-8")
        )
        supply_chain = json.loads(
            (APP_ROOT / "service" / "opendesign_supply_chain_0_16_1.json").read_text(encoding="utf-8")
        )

        self.assertEqual(routes["upstream"]["tag"], "open-design-v0.16.1")
        self.assertEqual(routes["upstream"]["commit"], "276b4d8e970bc143d7ad060181a89a834e3d9caf")
        self.assertEqual(routes["counts"]["total"], len(routes["routes"]))
        self.assertEqual(
            routes["counts"]["total"],
            sum(routes["counts"][key] for key in ("blocked", "handled_by_core", "pass_through")),
        )
        self.assertFalse([route for route in routes["routes"] if route["path_source"] == "unresolved"])

        route_policy = {
            (route["method"], route["path_template"], route["owner"]): route["classification"]
            for route in routes["routes"]
        }
        self.assertEqual(
            route_policy[("POST", "/api/runs", "apps/daemon/src/routes/runs.ts")],
            "pass_through",
        )
        self.assertEqual(
            route_policy[("GET", "/api/runs/{id}/events", "apps/daemon/src/routes/runs.ts")],
            "pass_through",
        )
        self.assertEqual(
            route_policy[("GET", "/api/runs/{id}/result-package", "apps/daemon/src/routes/runs.ts")],
            "pass_through",
        )
        self.assertEqual(
            route_policy[("POST", "/api/projects/{id}/terminals", "apps/daemon/src/routes/terminal.ts")],
            "blocked",
        )
        self.assertEqual(
            route_policy[("POST", "/api/import/folder", "apps/daemon/src/import-export-routes.ts")],
            "blocked",
        )
        self.assertEqual(
            route_policy[("GET", "/api/media/config", "apps/daemon/src/routes/media.ts")],
            "handled_by_core",
        )

        self.assertEqual(supply_chain["source_tree"]["tracked_file_count"], 11_458)
        self.assertEqual(supply_chain["source_tree"]["tracked_bytes"], 310_834_646)
        self.assertEqual(supply_chain["source_tree"]["package_count"], 27)
        self.assertEqual(
            supply_chain["source_tree"]["pnpm_lock_sha256"],
            "90bbe1375eb716240bbb79215c2a12a601abd977fe88587c6c6c6b4df31f6f23",
        )
        self.assertEqual(
            {dependency["name"] for dependency in supply_chain["native_runtime_dependencies"]},
            {"better-sqlite3", "node-pty", "blake3-wasm"},
        )

    def test_wp0_protocol_fixtures_cover_project_run_stream_and_terminal_results(self) -> None:
        create_request = self._fixture_json("project_create_request.json")
        create_response = self._fixture_json("project_create_response.json")
        projects_response = self._fixture_json("projects_response.json")
        run_request = self._fixture_json("run_create_request.json")
        run_response = self._fixture_json("run_create_response.json")

        self.assertEqual(create_response["project"]["id"], create_request["id"])
        self.assertEqual(projects_response["projects"][0]["id"], create_request["id"])
        self.assertEqual(run_request["projectId"], create_request["id"])
        self.assertEqual(run_response["conversationId"], create_response["conversationId"])
        self.assertEqual(run_request["agentId"], "maverick")

        event_blocks = (FIXTURES_ROOT / "run_events.sse").read_text(encoding="utf-8").strip().split("\n\n")
        event_ids: list[int] = []
        event_names: list[str] = []
        for block in event_blocks:
            fields = dict(line.split(": ", 1) for line in block.splitlines())
            event_ids.append(int(fields["id"]))
            event_names.append(fields["event"])
            self.assertIsInstance(json.loads(fields["data"]), dict)
        self.assertEqual(event_ids, sorted(event_ids))
        self.assertEqual(event_names[0], "start")
        self.assertEqual(event_names[-1], "end")

        terminal_results = [
            self._fixture_json("run_result_success.json"),
            self._fixture_json("run_result_failed.json"),
            self._fixture_json("run_result_canceled.json"),
        ]
        self.assertEqual(
            [result["run"]["status"] for result in terminal_results],
            ["succeeded", "failed", "canceled"],
        )
        for result in terminal_results:
            self.assertEqual(result["schema"], "open-design.run-result-package.v1")
            self.assertEqual(result["run"]["projectId"], create_request["id"])
            self.assertIsNone(result["events"]["logPath"])
        self.assertTrue(terminal_results[2]["run"]["cancelRequested"])

        acp_messages = [
            json.loads(line)
            for line in (FIXTURES_ROOT / "acp_session_transcript.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        methods = [message.get("method") for message in acp_messages if message.get("method")]
        self.assertEqual(methods[:3], ["initialize", "session/new", "session/prompt"])
        self.assertIn("session/update", methods)
        self.assertEqual(methods[-1], "session/cancel")

    def test_contract_declares_sandbox_sidecar_and_surfaces(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)

        self.assertEqual(parsed.app_id, "design-studio")
        self.assertEqual(parsed.contract.compatibility.supported_workspace_modes, ["sandbox"])
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.capabilities.skills, ["design-studio-ops"])
        self.assertEqual(parsed.contract.permissions.secrets.read, [])
        self.assertTrue(parsed.contract.permissions.providers.model_proxy)
        self.assertEqual(parsed.contract.permissions.providers.credential_source, "core-vault")
        self.assertFalse(parsed.contract.permissions.providers.deliver_secrets_to_app)
        sidecar = parsed.contract.services.http_sidecars[0]
        self.assertEqual(sidecar.service_id, "opendesign")
        self.assertEqual(sidecar.package_manager, "corepack/pnpm")
        self.assertEqual(sidecar.command, ["python3", "opendesign_launcher.py"])
        self.assertNotIn("MAVERICK_OPENDESIGN_ALLOW_FALLBACK", sidecar.env)
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

    def test_opendesign_launcher_fails_closed_without_bundle_even_if_fallback_is_requested(self) -> None:
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
                "MAVERICK_OPENDESIGN_ALLOW_FALLBACK": "1",
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
                configure_workspace_provider(
                    state.provider_store,
                    workspace_id="default",
                    provider_id="codex",
                    codex_command="/bin/echo",
                )
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
                    path="/api/apps/design-studio/sidecars/opendesign/api/provider/models",
                    method="POST",
                    body={
                        "protocol": "openai",
                        "baseUrl": "https://api.openai.com/v1",
                        "apiKey": "provider-fixture-token",
                    },
                    cookie=cookie,
                )
                direct_provider_status, direct_provider_body, _direct_provider_headers = self._invoke(
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
            direct_provider_payload = json.loads(direct_provider_body.decode("utf-8"))
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
            self.assertEqual(provider_status, 200)
            self.assertTrue(provider_payload["ok"])
            self.assertEqual(provider_payload["kind"], "success")
            self.assertTrue(provider_payload["models"])
            self.assertEqual(provider_payload["provider"]["provider_id"], "codex")
            self.assertFalse(provider_payload["sidecar_reached"])
            self.assertFalse(provider_payload["secrets_persisted"])
            self.assertNotIn("provider-fixture-token", provider_body.decode("utf-8"))
            self.assertEqual(direct_provider_status, 200)
            self.assertFalse(direct_provider_payload["ok"])
            self.assertEqual(direct_provider_payload["kind"], "unsupported_protocol")
            self.assertEqual(direct_provider_payload["status"], 404)
            self.assertFalse(direct_provider_payload["sidecar_reached"])
            self.assertFalse(direct_provider_payload["secrets_persisted"])
            self.assertNotIn("provider-fixture-token", direct_provider_body.decode("utf-8"))
            self.assertNotIn("provider-fixture-token", media_body.decode("utf-8"))
            self.assertNotIn("provider-fixture-token", state_body.decode("utf-8"))
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

    def test_provider_proxy_maps_missing_provider_to_opendesign_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self._test_platform_env():
                repo_root = self._temporary_repo_root(Path(temp_dir))
                state = bootstrap_platform_state(start_path=repo_root)
                with self._repo_pythonpath():
                    self._install_platform_app(state, repo_root, "design-studio")
                shutdown = EntrypointShutdownController()
                self.addCleanup(shutdown.begin_shutdown)
                app = PlatformHost(state, start_path=repo_root, shutdown_controller=shutdown)
                cookie = self._login(app)

            with self._repo_pythonpath():
                status, body, _headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/provider/models",
                    method="POST",
                    body={
                        "protocol": "openai",
                        "baseUrl": "https://api.openai.com/v1",
                        "apiKey": "provider-fixture-token",
                    },
                    cookie=cookie,
                )

            payload = json.loads(body.decode("utf-8"))
            media_config_root = (
                repo_root
                / "workspaces"
                / "default"
                / "data"
                / "design-studio"
                / "opendesign"
                / "media-config"
            )
            media_config_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in media_config_root.glob("*")
                if path.is_file()
            )

            self.assertEqual(status, 200)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["kind"], "upstream_unavailable")
            self.assertEqual(payload["status"], 503)
            self.assertFalse(payload["sidecar_reached"])
            self.assertFalse(payload["secrets_persisted"])
            self.assertNotIn("provider-fixture-token", body.decode("utf-8"))
            self.assertNotIn("provider-fixture-token", media_config_text)

    def _fixture_json(self, name: str) -> dict:
        return json.loads((FIXTURES_ROOT / name).read_text(encoding="utf-8"))

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
