"""Tests for the Design Studio app."""

from __future__ import annotations

from contextlib import contextmanager
from base64 import b64encode
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.dependencies import save_app_dependency_selection
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.contracts import parse_app_contract_file
from core.apps.sidecar_route_policy import route_policy_mode
from core.providers.service import configure_workspace_provider
from core.runtime.service import create_runtime_session
from core.runtime.runtime_threads import create_runtime_thread
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
            "handled_by_core",
        )
        self.assertEqual(
            route_policy[("GET", "/api/runs/{id}/events", "apps/daemon/src/routes/runs.ts")],
            "handled_by_core",
        )
        self.assertEqual(
            route_policy[("GET", "/api/runs/{id}/result-package", "apps/daemon/src/routes/runs.ts")],
            "handled_by_core",
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
        self.assertEqual(
            route_policy[("POST", "/api/provider/models", "apps/daemon/src/routes/chat.ts")],
            "handled_by_core",
        )
        self.assertFalse(
            [
                route
                for route in routes["routes"]
                if "{*" in route["path_template"] and route["classification"] != "blocked"
            ]
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
        self.assertTrue(parsed.contract.permissions.runtime.create_sessions)
        self.assertTrue(parsed.contract.permissions.runtime.cleanup_sessions)
        self.assertEqual(parsed.contract.entrypoints.hooks["runtime_event"], "backend/app_backend.py")
        sidecar = parsed.contract.services.http_sidecars[0]
        self.assertEqual(sidecar.service_id, "opendesign")
        self.assertIsNone(sidecar.package_manager)
        self.assertEqual(sidecar.command, ["python3", "opendesign_launcher.py"])
        self.assertNotIn("MAVERICK_OPENDESIGN_ALLOW_FALLBACK", sidecar.env)
        self.assertNotIn("OD_DATA_DIR", sidecar.env)
        self.assertNotIn("OD_MEDIA_CONFIG_DIR", sidecar.env)
        self.assertEqual(sidecar.env["OD_REQUIRE_API_TOKEN_ON_LOOPBACK"], "1")
        self.assertEqual(sidecar.env["DO_NOT_TRACK"], "1")
        self.assertEqual(sidecar.env["NEXT_TELEMETRY_DISABLED"], "1")
        self.assertEqual(sidecar.env["MAVERICK_OPENDESIGN_DATA_ROOT"], "${app.data_dir}/opendesign")
        self.assertEqual(
            sidecar.env["MAVERICK_OPENDESIGN_BUNDLE_ROOT"],
            "${app.source_dir}/service/vendor/open-design",
        )
        self.assertEqual(sidecar.bind.host, "127.0.0.1")
        self.assertEqual(sidecar.health.path, "/api/ready")
        self.assertEqual(sidecar.health.timeout_ms, 120_000)
        self.assertTrue(sidecar.proxy.streaming)
        self.assertTrue(sidecar.proxy.sse)
        self.assertFalse(sidecar.proxy.websocket)
        self.assertEqual(sidecar.entrypoint_access.ttl_seconds, 30)
        self.assertEqual(sidecar.entrypoint_access.request_budget, 16)
        self.assertFalse(sidecar.entrypoint_access.streaming)
        self.assertEqual(
            {surface.surface for surface in sidecar.entrypoint_access.surfaces},
            {"backend", "cli", "mcp", "reference"},
        )
        reference_access = next(
            surface for surface in sidecar.entrypoint_access.surfaces if surface.surface == "reference"
        )
        self.assertTrue(all(route.method in {"GET", "HEAD"} for route in reference_access.routes))
        pass_through = [rule.path_template for rule in sidecar.proxy.route_policy.pass_through]
        blocked = [rule.path_template for rule in sidecar.proxy.route_policy.blocked]
        handled_by_core = [rule.path_template for rule in sidecar.proxy.route_policy.handled_by_core]
        self.assertIn("/index.html", pass_through)
        self.assertIn("/", pass_through)
        self.assertIn("/api/projects", pass_through)
        self.assertIn("/api/dialog/open-folder", blocked)
        self.assertIn("/api/media/config", handled_by_core)
        self.assertIn("/api/provider/models", handled_by_core)
        self.assertIn("/api/runs", handled_by_core)
        self.assertIn("/api/runs/{id}/events", handled_by_core)
        self.assertTrue(all(rule.method for rule in sidecar.proxy.route_policy.pass_through))
        self.assertTrue(all(rule.method for rule in sidecar.proxy.route_policy.handled_by_core))
        policy = sidecar.proxy.route_policy
        self.assertEqual(route_policy_mode(policy, method="GET", path="/api/status"), "not_allowed")
        self.assertEqual(route_policy_mode(policy, method="GET", path="/api/projects/project-a"), "pass_through")
        self.assertEqual(
            route_policy_mode(policy, method="GET", path="/api/projects/project-a/terminals"),
            "blocked",
        )
        self.assertEqual(
            route_policy_mode(policy, method="GET", path="/api/projects/project-a/terminals/extra"),
            "not_allowed",
        )
        self.assertEqual(
            route_policy_mode(policy, method="GET", path="/_next/static/build/app.js"),
            "pass_through",
        )
        self.assertEqual(
            route_policy_mode(policy, method="POST", path="/api/system/open-external"),
            "blocked",
        )

    def test_frontend_is_a_full_bleed_isolated_origin_host(self) -> None:
        app_source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        api_source = (APP_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
        css_source = (APP_ROOT / "frontend" / "src" / "styles" / "main.css").read_text(encoding="utf-8")
        built_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((APP_ROOT / "frontend" / "dist" / "assets").glob("app-*.js"))
        )

        self.assertIn("/api/app-sidecars/browser-launch", api_source)
        self.assertIn("/.well-known/maverick-sidecar-bootstrap", api_source)
        self.assertIn('form.method = "POST"', app_source)
        self.assertIn('ticket.value = ""', app_source)
        self.assertIn("event.source === window.parent", app_source)
        self.assertIn("isTrustedSidecarMessage", app_source)
        self.assertIn('allow="fullscreen"', app_source)
        self.assertIn("height: 100dvh", css_source)
        self.assertNotIn("proxy_url", app_source + api_source + built_source)
        self.assertNotIn("localStorage", app_source + api_source + built_source)
        self.assertNotIn("location.hash", app_source + api_source + built_source)
        self.assertNotIn("state.projects", app_source)
        self.assertIn("/api/app-sidecars/browser-launch", built_source)

    def test_opendesign_inventory_matches_exact_contract_policy(self) -> None:
        policy_check = subprocess.run(
            [sys.executable, str(APP_ROOT / "service" / "sync_route_policy.py")],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(policy_check.returncode, 0, policy_check.stderr)

        manifest = json.loads((APP_ROOT / "service" / "opendesign_bundle.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["upstream"]["commit"], "276b4d8e970bc143d7ad060181a89a834e3d9caf")
        self.assertEqual(manifest["upstream"]["release_identity"]["package_version"], "0.16.1")
        self.assertEqual(manifest["distribution"]["primary"], "oci_import")
        self.assertEqual(
            manifest["distribution"]["index"]["digest"],
            "sha256:eb1c9d55532ffd2088a4a71951cffd273dff65e96e077bcef8c8bac3a6e1f1a1",
        )
        fallback_stage = manifest["fallback_build"]["stage"]
        self.assertEqual(fallback_stage["daemon_package"], "@open-design/daemon")
        self.assertEqual(fallback_stage["built_entrypoint"], "apps/daemon/dist/cli.js")
        self.assertEqual(fallback_stage["web_static_dir"], "apps/web/out")
        self.assertEqual(manifest["toolchain"]["package_manager"], "pnpm@10.33.2")
        self.assertEqual(set(manifest["sandbox"]), {"env"})

    def test_opendesign_launcher_fails_closed_without_bundle_even_if_fallback_is_requested(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "opendesign"
            env = {
                **os.environ,
                "PYTHONPATH": str(REPO_ROOT),
                "OD_BIND_HOST": "127.0.0.1",
                "OD_PORT": str(self._free_port()),
                "OD_API_TOKEN": "launcher-test-token",
                "OD_SANDBOX_MODE": "1",
                "MAVERICK_OPENDESIGN_DATA_ROOT": str(data_dir),
                "MAVERICK_OPENDESIGN_BUNDLE_ROOT": str(root / "missing-open-design"),
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

    def test_adapter_state_preserves_sealed_legacy_catalog_and_uses_od_ids(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data" / "design-studio"
            data_root.mkdir(parents=True)
            legacy_bytes = b'{"schema_version":"1","projects":[{"id":"design_0123456789ab"}]}\n'
            legacy_state = data_root / "state.json"
            legacy_state.write_bytes(legacy_bytes)
            legacy_state.chmod(0o400)
            state = self._run_entrypoint(
                APP_ROOT / "backend" / "app_backend.py",
                {
                    "surface": "backend",
                    "app_id": "design-studio",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "state"},
                },
            )
            adapter = json.loads((data_root / "adapter-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["json"]["state"]["schema_version"], "3")
            self.assertNotIn("projects", state["json"]["state"])
            self.assertNotIn("projects", adapter)
            self.assertEqual(legacy_state.read_bytes(), legacy_bytes)
            self.assertEqual(legacy_state.stat().st_mode & 0o777, 0o400)

            project = {"project": {"id": "od_project_adapter", "name": "Dashboard"}}
            with self._fake_app_sidecar_broker(project) as (descriptor, captured):
                imported = self._run_entrypoint(
                    APP_ROOT / "backend" / "app_backend.py",
                    {
                        "surface": "backend",
                        "app_id": "design-studio",
                        "workspace_id": "default",
                        "data_root": str(data_root),
                        "app_dependencies": {"storage-read": {"provider_app_ids": ["storage"]}},
                        "app_sidecar": descriptor,
                        "body": {
                            "action": "import_from_storage",
                            "arguments": {
                                "project_id": "od_project_adapter",
                                "workspace_relative_path": "storage/uploaded/brief.md",
                            },
                        },
                    },
                )
            self.assertEqual(captured["path"], "/api/projects/od_project_adapter")
            self.assertEqual(imported["json"]["od_project_id"], "od_project_adapter")
            self.assertEqual(imported["json"]["import"]["status"], "pending")
            request = imported["json"]["dependency_backend_requests"][0]
            self.assertEqual(request["dependency_alias"], "storage-read")
            self.assertNotIn("app_data_path", imported["json"]["import"])

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
            self.assertEqual(cli["state"]["schema_version"], "3")
            self.assertEqual(mcp["state"]["schema_version"], "3")
            self.assertEqual(cli["opendesign"]["version"], "0.16.1")
            self.assertEqual(mcp["opendesign"]["version"], "0.16.1")

    def test_backend_cli_mcp_and_reference_resolve_same_opendesign_id_through_sdk(self) -> None:
        project_response = self._fixture_json("project_create_response.json")
        project_id = project_response["project"]["id"]
        requests: list[dict] = []
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data" / "design-studio"
            payloads = [
                (
                    APP_ROOT / "backend" / "app_backend.py",
                    {
                        "surface": "backend",
                        "app_id": "design-studio",
                        "workspace_id": "default",
                        "data_root": str(data_root),
                        "body": {"action": "get_project", "arguments": {"project_id": project_id}},
                    },
                    lambda result: result["json"]["od_project_id"],
                ),
                (
                    APP_ROOT / "cli" / "app_cli.py",
                    {
                        "surface": "cli",
                        "command_id": "app.design-studio.design-studio",
                        "app_id": "design-studio",
                        "workspace_id": "default",
                        "data_root": str(data_root),
                        "arguments": {"action": "get_project", "project_id": project_id},
                    },
                    lambda result: result["od_project_id"],
                ),
                (
                    APP_ROOT / "mcp" / "server.py",
                    {
                        "surface": "mcp",
                        "tool_name": "design_studio_get_project",
                        "app_id": "design-studio",
                        "workspace_id": "default",
                        "data_root": str(data_root),
                        "arguments": {"project_id": project_id},
                    },
                    lambda result: result["od_project_id"],
                ),
                (
                    APP_ROOT / "mcp" / "server.py",
                    {
                        "surface": "mcp",
                        "tool_name": "design_studio_reference_resolve",
                        "app_id": "design-studio",
                        "workspace_id": "default",
                        "data_root": str(data_root),
                        "arguments": {"entity_type": "design_project", "entity_id": project_id},
                    },
                    lambda result: result["entity_id"],
                ),
            ]
            resolved_ids = []
            for entrypoint, payload, resolve_id in payloads:
                with self._fake_app_sidecar_broker(project_response) as (descriptor, captured):
                    result = self._run_entrypoint(entrypoint, {**payload, "app_sidecar": descriptor})
                requests.append(captured)
                resolved_ids.append(resolve_id(result))

        self.assertEqual(resolved_ids, [project_id] * 4)
        self.assertEqual([request["method"] for request in requests], ["GET"] * 4)
        self.assertEqual([request["path"] for request in requests], [f"/api/projects/{project_id}"] * 4)
        self.assertTrue(all(request["capability"] == "fixture-capability" for request in requests))
        self.assertNotIn("OD_API_TOKEN", json.dumps(requests))

    def test_runtime_thread_delete_completes_with_design_studio_enabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self._test_platform_env():
                repo_root = self._temporary_repo_root(Path(temp_dir))
                state = bootstrap_platform_state(start_path=repo_root)
                with self._repo_pythonpath():
                    self._install_platform_app(state, repo_root, "design-studio")
                session = create_runtime_session(
                    state.runtime_store,
                    session_id="chat-delete-test",
                    workspace_id="default",
                    agent_id="chat",
                    source_app_id="chat",
                    start_path=repo_root,
                )
                create_runtime_thread(
                    state.runtime_store,
                    workspace_id="default",
                    thread_id=session.session_id,
                    runtime_session_id=session.session_id,
                    title="Delete me",
                    source_app_id="chat",
                    now=session.updated_at,
                )
                shutdown = EntrypointShutdownController()
                self.addCleanup(shutdown.begin_shutdown)
                app = PlatformHost(state, start_path=repo_root, shutdown_controller=shutdown)
                cookie = self._login(app)

            with self._repo_pythonpath():
                status, body, _headers = self._invoke(
                    app,
                    path="/api/runtime/threads/chat-delete-test",
                    method="DELETE",
                    body={"reason": "chat_thread_deleted"},
                    cookie=cookie,
                )

            payload = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200, body.decode("utf-8"))
            self.assertEqual(payload["deleted_thread_id"], "chat-delete-test")
            self.assertEqual(
                payload["runtime_cleanup"]["app_cleanup"],
                [
                    {
                        "app_id": "design-studio",
                        "cleaned_runtime_session_ids": ["chat-delete-test"],
                        "deleted_conversation_bindings": 0,
                        "deleted_runtime_correlations": 0,
                    }
                ],
            )
            self.assertEqual(state.runtime_store.list_threads("default"), [])

    def test_hosted_backend_imports_through_storage_dependency_and_sidecar_callback(self) -> None:
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
                self.assertEqual(import_status, 200, import_body.decode("utf-8"))
                self.assertEqual(
                    [item["status"] for item in import_payload["dependency_backend_request_results"]],
                    ["completed"],
                )

                state_status, state_body, _state_headers = self._invoke_backend(
                    app,
                    cookie=cookie,
                    body={"action": "state"},
                )
            state_payload = json.loads(state_body.decode("utf-8"))
            self.assertEqual(import_status, 200, import_body.decode("utf-8"))
            final_import = state_payload["state"]["import_jobs"][0]
            self.assertEqual(state_status, 200)
            self.assertEqual(final_import["status"], "imported")
            self.assertEqual(final_import["workspace_relative_path"], "storage/uploaded/brief.md")
            self.assertEqual(len(final_import["sha256"]), 64)
            self.assertNotIn("app_data_path", final_import)
            self.assertNotIn("projects", state_payload["state"])

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
                config_status, config_body, _config_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/app-config",
                    cookie=cookie,
                )
                config_update_status, config_update_body, _config_update_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/app-config",
                    method="PUT",
                    body={
                        "onboardingCompleted": True,
                        "agentId": "maverick",
                        "skillId": "design-review",
                        "telemetry": {"metrics": False, "content": False, "artifactManifest": False},
                        "allowSilentUpdates": False,
                    },
                    cookie=cookie,
                )
                config_secret_status, config_secret_body, _config_secret_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/app-config",
                    method="PUT",
                    body={"agentCliEnv": {"codex": {"OPENAI_API_KEY": "must-not-persist"}}},
                    cookie=cookie,
                )
                attribution_status, attribution_body, _attribution_headers = self._invoke(
                    app,
                    path="/api/apps/design-studio/sidecars/opendesign/api/attribution/claim",
                    method="POST",
                    body={"token": "must-not-persist"},
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
            config_payload = json.loads(config_body.decode("utf-8"))
            config_update_payload = json.loads(config_update_body.decode("utf-8"))
            config_secret_payload = json.loads(config_secret_body.decode("utf-8"))
            attribution_payload = json.loads(attribution_body.decode("utf-8"))
            provider_payload = json.loads(provider_body.decode("utf-8"))
            direct_provider_payload = json.loads(direct_provider_body.decode("utf-8"))
            import_payload = json.loads(import_body.decode("utf-8"))
            terminal_payload = json.loads(terminal_body.decode("utf-8"))
            state_payload = json.loads(state_body.decode("utf-8"))
            media_config_root = repo_root / "workspaces" / "default" / "data" / "design-studio" / "opendesign" / "media-config"
            media_config_text = "\n".join(path.read_text(encoding="utf-8") for path in media_config_root.glob("*") if path.is_file())
            final_import = state_payload["state"]["import_jobs"][0]

            self.assertEqual(media_status, 200)
            self.assertFalse(media_payload["sidecar_reached"])
            self.assertFalse(media_payload["secrets_persisted"])
            self.assertEqual(config_status, 200)
            self.assertTrue(config_payload["config"]["onboardingCompleted"])
            self.assertEqual(config_payload["config"]["agentId"], "maverick")
            self.assertFalse(config_payload["config"]["telemetry"]["content"])
            self.assertEqual(config_update_status, 200)
            self.assertEqual(config_update_payload["config"]["skillId"], "design-review")
            self.assertEqual(config_secret_status, 400)
            self.assertEqual(config_secret_payload["error"], "app_config_field_not_allowed")
            self.assertNotIn("must-not-persist", config_secret_body.decode("utf-8"))
            self.assertEqual(attribution_status, 200)
            self.assertEqual(attribution_payload["status"], "invalid")
            self.assertFalse(attribution_payload["sidecar_reached"])
            self.assertNotIn("must-not-persist", attribution_body.decode("utf-8"))
            self.assertEqual(provider_status, 200)
            self.assertTrue(provider_payload["ok"])
            self.assertEqual(provider_payload["kind"], "success")
            self.assertTrue(provider_payload["models"])
            self.assertEqual(provider_payload["provider"]["provider_id"], "codex")
            self.assertFalse(provider_payload["sidecar_reached"])
            self.assertFalse(provider_payload["secrets_persisted"])
            self.assertNotIn("provider-fixture-token", provider_body.decode("utf-8"))
            self.assertEqual(direct_provider_status, 404)
            self.assertEqual(direct_provider_payload["error"], "sidecar_route_not_allowed")
            self.assertNotIn("provider-fixture-token", direct_provider_body.decode("utf-8"))
            self.assertNotIn("provider-fixture-token", media_body.decode("utf-8"))
            self.assertNotIn("provider-fixture-token", state_body.decode("utf-8"))
            self.assertNotIn("must-not-persist", state_body.decode("utf-8"))
            self.assertNotIn("provider-fixture-token", media_config_text)
            self.assertEqual(import_status, 200)
            self.assertEqual(
                [item["status"] for item in import_payload["dependency_backend_request_results"]],
                ["completed"],
            )
            self.assertEqual(terminal_status, 403)
            self.assertEqual(terminal_payload["error"], "sidecar_route_blocked")
            self.assertEqual(state_status, 200)
            self.assertEqual(final_import["status"], "imported")
            self.assertNotIn("projects", state_payload["state"])

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

    @contextmanager
    def _fake_app_sidecar_broker(self, response_payload: dict):
        with TemporaryDirectory() as temp_dir:
            socket_path = str(Path(temp_dir) / "broker.sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(socket_path)
            server.listen(1)
            server.settimeout(5)
            captured: dict = {}

            def serve() -> None:
                try:
                    connection, _address = server.accept()
                    with connection:
                        wire = b""
                        while not wire.endswith(b"\n"):
                            wire += connection.recv(65536)
                        captured.update(json.loads(wire.decode("utf-8")))
                        response = {
                            "ok": True,
                            "status_code": 200,
                            "headers": {"content-type": "application/json"},
                            "body_base64": b64encode(json.dumps(response_payload).encode("utf-8")).decode("ascii"),
                        }
                        connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
                finally:
                    server.close()

            thread = Thread(target=serve, daemon=True)
            thread.start()
            descriptor = {
                "protocol": "maverick.app-sidecar.v1",
                "invocation_id": "fixture-invocation",
                "services": {
                    "opendesign": {
                        "broker_socket": socket_path,
                        "capability": "fixture-capability",
                        "expires_in_seconds": 30,
                        "request_budget": 1,
                        "max_request_body_bytes": 65536,
                        "max_response_body_bytes": 8388608,
                        "streaming": False,
                    }
                },
            }
            yield descriptor, captured
            thread.join(timeout=6)
            self.assertFalse(thread.is_alive())

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
        if app_id == "design-studio":
            contract_path = target / "app_contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            sidecar = contract["services"]["http_sidecars"][0]
            sidecar["working_directory"] = "."
            sidecar["command"] = ["python3", "tests/fixtures/opendesign_test_server.py"]
            contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

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
