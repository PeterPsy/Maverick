"""Tests for the native agents app."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
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
from core.skills.service import list_visible_platform_skills


AGENTS_BACKEND = Path(__file__).resolve().parents[1] / "apps" / "agents" / "backend"
sys.path.insert(0, str(AGENTS_BACKEND))

from seeds import seed_defaults
from service import handle_action
from store import delete_role, list_agent_types, list_roles


class AgentsAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "local-skills", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[1] / "apps"
        for app_id in ("base-shell", "chat", "agents"):
            shutil.copytree(source_apps_root / app_id, repo_root / "apps" / app_id, ignore=shutil.ignore_patterns("node_modules"))
        return repo_root

    def invoke(self, app, *, path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict | bytes]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        raw = b"".join(
            app(
                {
                    "PATH_INFO": path,
                    "REQUEST_METHOD": method,
                    "CONTENT_LENGTH": str(len(payload)),
                    "CONTENT_TYPE": "application/json",
                    "wsgi.input": BytesIO(payload),
                },
                start_response,
            )
        )
        status = int(headers["__status__"].split()[0])
        content_type = headers.get("Content-Type", "")
        if "application/json" in content_type:
            return status, json.loads(raw.decode("utf-8"))
        return status, raw

    def test_contract_declares_agents_surfaces(self) -> None:
        parsed = parse_app_contract_file(Path(__file__).resolve().parents[1] / "apps" / "agents")

        self.assertEqual(parsed.app_id, "agents")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertEqual(parsed.contract.capabilities.mcp_tools, ["maverick_agents_app"])
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["agents"])
        self.assertEqual(parsed.contract.capabilities.skills, ["agents-ops"])

    def test_seed_defaults_create_all_roles_and_agent_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "agents"
            result = seed_defaults(data_root)

            self.assertEqual(result["role_count"], 17)
            self.assertEqual(result["agent_type_count"], 17)
            self.assertEqual(len(list_roles(data_root)), 17)
            self.assertEqual(len(list_agent_types(data_root)), 17)
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
            self.assertEqual(len(payload["roles"]), 17)
            self.assertIn("Server Coding Engineer", preview_payload["rendered"])
            self.assertNotIn("instances", payload)

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
                    "codex_skill_ids": [],
                    "execution_mode_policy": "fixed",
                    "default_execution_mode": "sandbox",
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
            self.assertEqual(delete_status, 200)
            self.assertEqual(delete_payload, {"deleted": True})

    def test_bootstrap_installs_agents_and_exposes_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        self.assertIn("agents", {binding.app_id for binding in bindings})
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "agents" / "agent_types.json").is_file())

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        skills = list_visible_platform_skills(app_store=state.app_store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.agents.maverick_agents_app", [tool.tool_name for tool in tools])
        self.assertIn("app.agents.agents", [command.command_id for command in commands])
        self.assertIn("app.agents.agents-ops", [skill.skill_id for skill in skills])

    def test_platform_backend_mount_returns_agents_catalog(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status, payload = self.invoke(app, path="/api/apps/agents/backend", method="POST", body={"action": "catalog"})

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["roles"]), 17)
        self.assertEqual(len(payload["agent_types"]), 17)

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
