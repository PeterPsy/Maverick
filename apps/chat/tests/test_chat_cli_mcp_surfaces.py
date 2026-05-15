from __future__ import annotations

from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools
from core.shared.entrypoints import run_json_entrypoint
from tests.support.markers import integration_test
from tests.support.repo import link_app_sources, make_temp_repo_root


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / "apps" / "chat"
CHAT_BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(CHAT_BACKEND_ROOT))

from chat_state import create_project, mutate_state, state_path  # noqa: E402
from service import handle_action  # noqa: E402


class ChatCliMcpSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def make_repo_root(self) -> Path:
        repo_root = make_temp_repo_root(self, include_core=True)
        link_app_sources(repo_root, ["chat"])
        return repo_root

    def run_cli_entrypoint(self, data_root: Path, arguments: dict) -> dict:
        return run_json_entrypoint(
            APP_ROOT / "cli" / "app_cli.py",
            payload={
                "workspace_id": "default",
                "app_id": "chat",
                "data_root": str(data_root),
                "arguments": arguments,
            },
            cwd=APP_ROOT,
        )

    def run_mcp_entrypoint(self, data_root: Path, tool_name: str, arguments: dict) -> dict:
        return run_json_entrypoint(
            APP_ROOT / "mcp" / "server.py",
            payload={
                "workspace_id": "default",
                "app_id": "chat",
                "data_root": str(data_root),
                "tool_name": tool_name,
                "arguments": arguments,
            },
            cwd=APP_ROOT,
        )

    def test_contract_declares_only_operational_chat_mcp_tools(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        tools = set(parsed.contract.capabilities.mcp_tools)

        self.assertNotIn("message.send", tools)
        self.assertNotIn("turn.stop", tools)
        self.assertIn("chat_operations_manifest", tools)
        self.assertIn("chat_reference_search", tools)
        self.assertTrue((APP_ROOT / "cli" / "command_schemas.json").is_file())
        self.assertTrue((APP_ROOT / "mcp" / "tool_schemas.json").is_file())

    def test_default_action_returns_compact_operations_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            status, payload = handle_action(Path(temp) / "chat", {})

            self.assertEqual(status, 200)
            self.assertEqual(payload["default_action"], "operations.manifest")
            self.assertIn("references.search", payload["operations"])
            self.assertIn("projects.list", payload["operations"])
            self.assertLess(len(json.dumps(payload)), 5000)

    def test_mcp_operations_manifest_matches_cli_default_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "chat"

            cli_result = self.run_cli_entrypoint(data_root, {})
            mcp_result = self.run_mcp_entrypoint(data_root, "chat_operations_manifest", {})

            self.assertEqual(cli_result["status_code"], 200)
            self.assertEqual(mcp_result["status_code"], 200)
            self.assertEqual(cli_result["default_action"], "operations.manifest")
            self.assertEqual(mcp_result["default_action"], "operations.manifest")
            self.assertEqual(cli_result["operations"], mcp_result["operations"])

    def test_mcp_operations_manifest_rejects_unexpected_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_mcp_entrypoint(Path(temp) / "chat", "chat_operations_manifest", {"extra": True})

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "validation_error")
            self.assertIn("Unexpected field", result["detail"])
            self.assertEqual(result["allowed_values"]["fields"], [])

    def test_reference_search_and_resolve_share_cli_mcp_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "chat"
            path = state_path(data_root)
            mutate_state(path, lambda current: {"project": create_project(current, {"name": "Client Work"})})

            cli_result = self.run_cli_entrypoint(
                data_root,
                {"action": "references.search", "entity_type": "project", "query": "client"},
            )
            mcp_result = self.run_mcp_entrypoint(
                data_root,
                "chat_reference_search",
                {"entity_type": "project", "query": "client"},
            )
            project_id = cli_result["results"][0]["entity_id"]
            resolved = self.run_mcp_entrypoint(
                data_root,
                "chat_reference_resolve",
                {"entity_type": "project", "project_id": project_id},
            )

            self.assertEqual(cli_result["status_code"], 200)
            self.assertEqual(mcp_result["status_code"], 200)
            self.assertEqual(cli_result["results"], mcp_result["results"])
            self.assertEqual(resolved["status_code"], 200)
            self.assertTrue(resolved["exists"])
            self.assertEqual(resolved["entity_id"], project_id)
            self.assertIn("/app/chat/projects/", resolved["deep_link"])

    def test_cli_unknown_action_returns_guided_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_cli_entrypoint(Path(temp) / "chat", {"action": "unknown.action"})

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "unsupported_action")
            self.assertIn("allowed_values", result)
            self.assertEqual(result["example"], {"action": "operations.manifest"})

    def test_cli_rejects_backend_only_project_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "chat"
            result = self.run_cli_entrypoint(data_root, {"action": "projects.create", "name": "Probe"})
            status, projects = handle_action(data_root, {"action": "projects.list"})

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "unsupported_action")
            self.assertNotIn("projects.create", result["allowed_values"]["action"])
            self.assertEqual(status, 200)
            self.assertEqual(projects["projects"], [])

    def test_cli_rejects_fields_outside_command_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_cli_entrypoint(Path(temp) / "chat", {"action": "operations.manifest", "extra": True})

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "validation_error")
            self.assertIn("Unexpected field", result["detail"])
            self.assertIn("action", result["allowed_values"]["fields"])

    def test_mcp_validation_error_explains_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_mcp_entrypoint(Path(temp) / "chat", "chat_reference_resolve", {"entity_type": "project"})

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "validation_error")
            self.assertEqual(result["expected_fields"], ["entity_id"])
            self.assertIn("project_id", result["accepted_aliases"]["entity_id"])

    def test_custom_view_rejects_malformed_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_mcp_entrypoint(
                Path(temp) / "chat",
                "chat_set_custom_view",
                {"refs": [{"entity_type": "project"}]},
            )

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "validation_error")
            self.assertEqual(result["expected_fields"], ["refs[0].entity_type", "refs[0].entity_id"])
            self.assertEqual(result["allowed_values"]["refs[].entity_type"], ["project", "thread"])

    def test_custom_view_rejects_refs_with_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_mcp_entrypoint(
                Path(temp) / "chat",
                "chat_set_custom_view",
                {"refs": [{"entity_type": "project", "entity_id": "project-uuid", "label": "extra"}]},
            )

            self.assertEqual(result["status_code"], 400)
            self.assertEqual(result["error"], "validation_error")
            self.assertIn("Unexpected field", result["detail"])
            self.assertEqual(result["allowed_values"]["refs[].fields"], ["entity_type", "entity_id"])

    @integration_test("chat platform integration suite; run with scripts/test_suite.py --area app --app chat")
    def test_platform_cli_and_mcp_inspect_use_chat_sidecars(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        command = next(
            item
            for item in list_core_cli_commands(
                app_store=state.app_store,
                workspace_id="default",
                start_path=repo_root,
            )
            if item.command_id == "app.chat.chat"
        )
        tool = next(
            item
            for item in list_mcp_tools(
                app_store=state.app_store,
                workspace_id="default",
                start_path=repo_root,
            )
            if item.tool_name == "app.chat.chat_reference_search"
        )

        self.assertIn("project references", command.description)
        self.assertIn("operations.manifest", command.argument_schema["properties"]["action"]["enum"])
        self.assertNotIn("projects.create", command.argument_schema["properties"]["action"]["enum"])
        self.assertIn("Search Chat project references", tool.description)
        self.assertEqual(tool.input_schema["required"], ["entity_type"])
        self.assertEqual(tool.input_schema["properties"]["limit"]["maximum"], 50)

    @integration_test("chat platform integration suite; run with scripts/test_suite.py --area app --app chat")
    def test_platform_cli_default_and_mcp_reference_search(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        data_root = repo_root / "workspaces" / "default" / "data" / "chat"
        mutate_state(state_path(data_root), lambda current: {"project": create_project(current, {"name": "Client Work"})})
        cli_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="tester",
            effective_mode="sandbox",
        )
        mcp_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="tester",
            effective_mode="sandbox",
        )

        cli_manifest = run_core_cli_command(
            command_id="app.chat.chat",
            context=cli_context,
            arguments={},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        mcp_search = call_mcp_tool(
            tool_name="app.chat.chat_reference_search",
            context=mcp_context,
            arguments={"entity_type": "project", "query": "client"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(cli_manifest["default_action"], "operations.manifest")
        self.assertEqual(mcp_search["status_code"], 200)
        self.assertEqual(mcp_search["results"][0]["title"], "Client Work")


if __name__ == "__main__":
    unittest.main()
