"""Tests for the native Dynamic Views app."""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools
from core.shared.entrypoints import run_json_entrypoint
from tests.support.markers import integration_test


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_VIEWS_ROOT = REPO_ROOT / "apps" / "dynamic-views"


class DynamicViewsAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        source_apps_root = REPO_ROOT / "apps"
        for app_id in ("base-shell", "chat", "dynamic-views"):
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
        cookie: str | None = None,
        query_string: str = "",
    ) -> tuple[int, dict | bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": query_string,
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        raw = b"".join(app(environ, start_response))
        status = int(headers["__status__"].split()[0])
        if "application/json" in headers.get("Content-Type", ""):
            return status, json.loads(raw.decode("utf-8")), headers
        return status, raw, headers

    def login(self, app) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def run_backend(self, *, data_root: Path, body: dict, workspace_id: str = "default") -> dict:
        return run_json_entrypoint(
            DYNAMIC_VIEWS_ROOT / "backend" / "app_backend.py",
            payload={"data_root": str(data_root), "workspace_id": workspace_id, "body": body},
            cwd=DYNAMIC_VIEWS_ROOT,
        )

    def test_backend_rejects_missing_workspace_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = run_json_entrypoint(
                DYNAMIC_VIEWS_ROOT / "backend" / "app_backend.py",
                payload={"data_root": str(Path(temp) / "dynamic-views"), "body": {"action": "list"}},
                cwd=DYNAMIC_VIEWS_ROOT,
            )

        self.assertEqual(result["status_code"], 400)
        self.assertEqual(result["json"]["error"], "workspace_id_required")

    def sample_create_payload(self) -> dict:
        return {
            "action": "create",
            "payload": {
                "title": "Revenue Probe",
                "summary": "Mini dashboard",
                "package": {
                    "renderer": "sandbox_html_v1",
                    "html": "<main><h1>Revenue</h1><div id=\"root\"></div></main>",
                    "css": "body { font-family: system-ui; }",
                    "javascript": "document.getElementById('root').textContent = window.MaverickDynamicView.data.value;",
                    "tags": ["finance"],
                },
                "data": {"value": 42},
                "dataBindings": [{"sourceType": "inline", "sourceRef": "revenue", "snapshot": {"value": 42}}],
                "snapshotMode": "snapshot",
            },
        }

    def test_contract_declares_dynamic_views_surfaces(self) -> None:
        parsed = parse_app_contract_file(DYNAMIC_VIEWS_ROOT)

        self.assertEqual(parsed.app_id, "dynamic-views")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("maverick_dynamic_views", parsed.contract.capabilities.mcp_tools)
        self.assertIn("dynamic_views_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertIn("dynamic_views_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["dynamic-views"])
        self.assertIn("view", {item.entity_type for item in parsed.contract.capabilities.reference_entities})
        self.assertEqual(parsed.contract.capabilities.skills, ["dynamic-views"])
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "dynamic-views")
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].entity_types, ["view"])
        self.assertEqual(len(parsed.contract.widgets), 1)
        widget = parsed.contract.widgets[0]
        self.assertEqual(widget.widget_id, "dynamic-view")
        self.assertEqual(widget.host, "chat")
        self.assertEqual(widget.content_kinds, ["dynamic.view.instance"])
        self.assertEqual(widget.frontend.mount, "frontend/dist/widgets/dynamic-view")
        self.assertTrue(widget.actions.cli)
        self.assertTrue((DYNAMIC_VIEWS_ROOT / "frontend" / "dist" / "widgets" / "dynamic-view" / "index.html").is_file())

    def test_backend_creates_lists_reads_and_deletes_dynamic_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "data" / "dynamic-views"

            created = self.run_backend(data_root=data_root, body=self.sample_create_payload())
            listed = self.run_backend(data_root=data_root, body={"action": "list"})
            instance_id = created["json"]["instance"]["id"]
            read = self.run_backend(data_root=data_root, body={"action": "read", "id": instance_id})
            deleted = self.run_backend(data_root=data_root, body={"action": "delete", "id": instance_id})

            self.assertEqual(created["status_code"], 200)
            self.assertEqual(created["json"]["chat_render"]["kind"], "dynamic.view.instance")
            self.assertEqual(created["json"]["instance"]["package"]["security_report"]["status"], "approved")
            self.assertTrue((data_root / "state.json").is_file())
            self.assertEqual(len(list((data_root / "assets").iterdir())), 1)
            self.assertEqual(listed["json"]["items"][0]["id"], instance_id)
            self.assertEqual(read["json"]["instance"]["title"], "Revenue Probe")
            self.assertEqual(deleted["json"]["deleted"], 1)

    def test_backend_rejects_blocked_source(self) -> None:
        payload = self.sample_create_payload()
        payload["payload"]["package"]["javascript"] = "fetch('/api/secret')"
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_backend(data_root=Path(temp) / "data" / "dynamic-views", body=payload)

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["json"]["error"], "validation_error")

    @integration_test("dynamic-views platform integration suite; run with scripts/test_suite.py --level integration")
    def test_bootstrap_installs_dynamic_views_and_exposes_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        self.assertIn("dynamic-views", {binding.app_id for binding in bindings})
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "dynamic-views" / "state.json").is_file())

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.dynamic-views.maverick_dynamic_views", [tool.tool_name for tool in tools])
        self.assertIn("app.dynamic-views.dynamic-views", [command.command_id for command in commands])

    @integration_test("dynamic-views platform integration suite; run with scripts/test_suite.py --level integration")
    def test_platform_backend_frontend_and_widget_mount(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        backend_status, backend_payload, _backend_headers = self.invoke(
            app,
            path="/api/apps/dynamic-views/backend",
            method="POST",
            body=self.sample_create_payload(),
            cookie=cookie,
        )
        frontend_status, frontend_payload, frontend_headers = self.invoke(app, path="/apps/dynamic-views/", cookie=cookie)
        registry_status, registry_payload, _registry_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=chat&content_kind=dynamic.view.instance",
            cookie=cookie,
        )
        mount_status, mount_payload, mount_headers = self.invoke(
            app,
            path="/api/apps/widgets/dynamic-views/dynamic-view/frontend/",
            cookie=cookie,
        )

        self.assertEqual(backend_status, 200)
        self.assertEqual(backend_payload["chat_render"]["kind"], "dynamic.view.instance")
        self.assertEqual(frontend_status, 200)
        self.assertIn("text/html", frontend_headers["Content-Type"])
        self.assertIn(b"Maverick Dynamic Views", frontend_payload)
        self.assertEqual(registry_status, 200)
        self.assertEqual(registry_payload["items"][0]["owner_app_id"], "dynamic-views")
        self.assertEqual(registry_payload["items"][0]["widget_id"], "dynamic-view")
        self.assertEqual(mount_status, 200)
        self.assertIn("text/html", mount_headers["Content-Type"])
        self.assertIn(b"Dynamic view widget", mount_payload)

    @integration_test("dynamic-views platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_and_cli_create_dynamic_view(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        mcp_payload = call_mcp_tool(
            tool_name="app.dynamic-views.maverick_dynamic_views",
            context=McpInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments=self.sample_create_payload(),
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_payload = run_core_cli_command(
            command_id="app.dynamic-views.dynamic-views",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "list"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertEqual(mcp_payload["chat_render"]["kind"], "dynamic.view.instance")
        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual(cli_payload["items"][0]["title"], "Revenue Probe")

    @integration_test("dynamic-views platform integration suite; run with scripts/test_suite.py --level integration")
    def test_cli_creates_and_reads_dynamic_view(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="tester",
            effective_mode="sandbox",
        )

        created = run_core_cli_command(
            command_id="app.dynamic-views.dynamic-views",
            context=context,
            arguments=self.sample_create_payload(),
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        read = run_core_cli_command(
            command_id="app.dynamic-views.dynamic-views",
            context=context,
            arguments={"action": "read", "id": created["instance"]["id"]},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(created["status_code"], 200)
        self.assertEqual(created["chat_render"]["kind"], "dynamic.view.instance")
        self.assertEqual(read["status_code"], 200)
        self.assertEqual(read["chat_render"]["payload"]["id"], created["instance"]["id"])


if __name__ == "__main__":
    unittest.main()
