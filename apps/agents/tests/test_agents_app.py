"""Tests for the native agents app."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools
from tests.support.markers import integration_test


AGENTS_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(AGENTS_BACKEND))

from seeds import seed_defaults
from service import app_events_for_action, handle_action
from store import delete_role, list_agent_types, list_roles


class AgentsAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[3] / "apps"
        for app_id in ("base-shell", "chat", "agents"):
            shutil.copytree(source_apps_root / app_id, repo_root / "apps" / app_id, ignore=shutil.ignore_patterns("node_modules"))
        return repo_root

    def invoke(self, app, *, path: str, method: str = "GET", body: dict | None = None, cookie: str | None = None) -> tuple[int, dict | bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        raw = b"".join(app(environ, start_response))
        status = int(headers["__status__"].split()[0])
        content_type = headers.get("Content-Type", "")
        if "application/json" in content_type:
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

    def test_contract_declares_agents_surfaces(self) -> None:
        parsed = parse_app_contract_file(Path(__file__).resolve().parents[1])

        self.assertEqual(parsed.app_id, "agents")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("maverick_agents_app", parsed.contract.capabilities.mcp_tools)
        self.assertIn("agents_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertIn("agents_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["agents"])
        self.assertEqual(parsed.contract.capabilities.skills, ["agents-ops"])
        self.assertIn("widget", parsed.contract.provides[0].surfaces)
        self.assertEqual(
            {widget.widget_id for widget in parsed.contract.widgets},
            {"agents-sidebar", "agents-sidebar-footer"},
        )
        self.assertIn("agent_type", {item.entity_type for item in parsed.contract.capabilities.reference_entities})
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "agents")
        self.assertEqual(
            [item.action for item in parsed.contract.capabilities.view_surfaces[0].state_actions],
            ["view_filter", "set_view_filter", "set_custom_view", "clear_custom_view"],
        )

    def test_seed_defaults_create_all_roles_and_agent_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            result = seed_defaults(data_root)

            self.assertEqual(result["role_count"], 14)
            self.assertEqual(result["agent_type_count"], 14)
            self.assertEqual(len(list_roles(data_root)), 14)
            self.assertEqual(len(list_agent_types(data_root)), 14)
            self.assertTrue((data_root / "roles" / "server-coding-engineer" / "ROLE.md").is_file())

    def test_service_rejects_deleting_referenced_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            seed_defaults(data_root)

            with self.assertRaises(ValueError):
                delete_role(data_root, "server-coding-engineer")

    def test_backend_catalog_and_prompt_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            status, payload = handle_action(data_root, {"action": "catalog"})
            preview_status, preview_payload = handle_action(
                data_root,
                {"action": "preview_prompt", "agent_type_id": "agent-type-server-coding-engineer"},
            )

            self.assertEqual(status, 200)
            self.assertEqual(preview_status, 200)
            self.assertEqual(len(payload["roles"]), 14)
            self.assertIn("Server Coding Engineer", preview_payload["rendered"])
            self.assertNotIn("instances", payload)
            self.assertNotIn("default_execution_mode", payload["agent_types"][0])
            self.assertNotIn("execution_mode_policy", payload["agent_types"][0])
            self.assertNotIn("Execution mode", preview_payload["rendered"])
            self.assertNotIn("Execution policy", preview_payload["rendered"])

    def test_backend_creates_and_deletes_agent_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            seed_defaults(data_root)

            create_status, create_payload = handle_action(
                data_root,
                {
                    "action": "create_agent_type",
                    "id": "agent-type-custom-test",
                    "name": "Custom Test Agent",
                    "description": "Temporary test agent.",
                    "role_id": "agent-builder",
                    "skill_ids": [],
                    "trace_verbosity": "compact",
                    "enabled": True,
                },
            )
            delete_status, delete_payload = handle_action(
                data_root,
                {"action": "delete_agent_type", "agent_type_id": "agent-type-custom-test"},
            )
            self.assertEqual(create_status, 200)
            self.assertEqual(create_payload["agent_type"]["id"], "agent-type-custom-test")
            self.assertIn("skill_ids", create_payload["agent_type"])
            self.assertNotIn("codex_skill_ids", create_payload["agent_type"])
            self.assertNotIn("default_execution_mode", create_payload["agent_type"])
            self.assertNotIn("execution_mode_policy", create_payload["agent_type"])
            self.assertEqual(delete_status, 200)
            self.assertEqual(delete_payload, {"deleted": True})

    def test_agents_app_does_not_own_runtime_launch(self) -> None:
        frontend_api = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
        frontend_types = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
        frontend_app = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

        self.assertNotIn("/api/runtime/sessions", frontend_api)
        self.assertNotIn("createRuntimeSession", frontend_api)
        self.assertNotIn("openChatForRuntimeSession", frontend_api)
        self.assertNotIn("Use In Runtime", frontend_app)
        self.assertNotIn("requested_mode", frontend_api)
        self.assertNotIn("default_execution_mode", frontend_types)
        self.assertNotIn("execution_mode_policy", frontend_types)

    def test_frontend_uses_shell_sidebar_widgets(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        frontend_app = (app_root / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        sidebar_widget = (app_root / "frontend" / "src" / "widgets" / "agents-sidebar" / "main.tsx").read_text(encoding="utf-8")
        footer_widget = (app_root / "frontend" / "src" / "widgets" / "agents-sidebar-footer" / "main.tsx").read_text(encoding="utf-8")

        self.assertNotIn("<AgentsSidebar", frontend_app)
        self.assertIn("maverick.app.navigate", frontend_app)
        self.assertIn("maverick.app.selection-changed", (app_root / "frontend" / "src" / "lib" / "activeAgentSelection.ts").read_text(encoding="utf-8"))
        self.assertIn("agentTypeIdFromWidgetContext", sidebar_widget)
        self.assertIn("useShellSidebarCloseSwipe", sidebar_widget)
        self.assertIn("maverick.widget.open-app", sidebar_widget)
        self.assertIn("agent-types/${agentTypeId}", sidebar_widget)
        self.assertIn("maverick.shell.sidebar.close", sidebar_widget)
        self.assertIn("new_agent_request_id", footer_widget)

    def test_backend_persists_agents_view_filter_and_custom_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            seed_defaults(data_root)

            filtered_status, filtered = handle_action(
                data_root,
                {"action": "set_view_filter", "query": "engineer", "entity_type": "agent_type"},
            )
            custom_status, custom = handle_action(
                data_root,
                {
                    "action": "set_custom_view",
                    "title": "Core builders",
                    "refs": [
                        {"entity_type": "agent_type", "entity_id": "agent-type-agent-builder"},
                        {"entity_type": "role_prompt", "entity_id": "server-coding-engineer"},
                    ],
                },
            )
            read_status, view_state = handle_action(data_root, {"action": "view_filter"})
            cleared_status, cleared = handle_action(data_root, {"action": "clear_custom_view"})

            self.assertEqual(filtered_status, 200)
            self.assertEqual(filtered["state"]["view_filter"]["query"], "engineer")
            self.assertEqual(filtered["state"]["view_filter"]["entity_type"], "agent_type")
            self.assertEqual(custom_status, 200)
            self.assertEqual(custom["state"]["view_filter"]["mode"], "custom")
            self.assertEqual(len(custom["state"]["view_filter"]["refs"]), 2)
            self.assertEqual(read_status, 200)
            self.assertEqual(view_state["state"]["view_filter"]["mode"], "custom")
            self.assertEqual(cleared_status, 200)
            self.assertEqual(cleared["state"]["view_filter"]["mode"], "search")

    def test_reading_agents_view_filter_does_not_emit_data_changed_event(self) -> None:
        self.assertEqual(app_events_for_action("view_filter"), [])
        self.assertEqual(app_events_for_action("set_view_filter"), [{"type": "maverick.app.data-changed", "resource": "view-state"}])

    @integration_test("agents platform integration suite; run with scripts/test_suite.py --level integration")
    def test_bootstrap_installs_agents_and_exposes_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        self.assertIn("agents", {binding.app_id for binding in bindings})
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "agents" / "agent_types.json").is_file())

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.agents.maverick_agents_app", [tool.tool_name for tool in tools])
        self.assertIn("app.agents.agents", [command.command_id for command in commands])

    @integration_test("agents platform integration suite; run with scripts/test_suite.py --level integration")
    def test_platform_backend_mount_returns_agents_catalog(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(app, path="/api/apps/agents/backend", method="POST", body={"action": "catalog"}, cookie=cookie)

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["roles"]), 17)
        self.assertEqual(len(payload["agent_types"]), 17)

    @integration_test("agents platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_and_cli_call_catalog(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        mcp_payload = call_mcp_tool(
            tool_name="app.agents.maverick_agents_app",
            context=McpInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "catalog"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_payload = run_core_cli_command(
            command_id="app.agents.agents",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "catalog"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual(len(mcp_payload["roles"]), 17)
        self.assertEqual(len(cli_payload["agent_types"]), 17)


if __name__ == "__main__":
    unittest.main()
