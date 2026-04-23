"""Tests for the native Skills app."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import importlib
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
from core.skills.service import list_available_workspace_skills


SKILLS_BACKEND = Path(__file__).resolve().parents[1] / "apps" / "skills" / "backend"


def load_skills_backend_modules():
    """Load app backend modules despite generic app-local module names."""
    sys.path.insert(0, str(SKILLS_BACKEND))
    for module_name in ("models", "store", "seeds", "service"):
        sys.modules.pop(module_name, None)
    store = importlib.import_module("store")
    service = importlib.import_module("service")
    return service, store


class SkillsAppTestCase(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[1] / "apps"
        for app_id in ("base-shell", "chat", "agents", "skills"):
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

    def test_contract_declares_skills_surfaces(self) -> None:
        parsed = parse_app_contract_file(Path(__file__).resolve().parents[1] / "apps" / "skills")

        self.assertEqual(parsed.app_id, "skills")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("maverick_skills_app", parsed.contract.capabilities.mcp_tools)
        self.assertIn("skills_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["skills"])
        self.assertEqual(parsed.contract.capabilities.skills, [])
        self.assertIn("skill", {item.entity_type for item in parsed.contract.capabilities.reference_entities})

    def test_service_creates_updates_and_deletes_skill(self) -> None:
        service, _store = load_skills_backend_modules()
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "skills"
            create_status, create_payload = service.handle_action(
                data_root,
                {
                    "action": "create_skill",
                    "id": "marketing-launch",
                    "name": "Marketing Launch",
                    "description": "Use for campaign launch planning.",
                    "content": "Plan launch positioning, channels, owners, and next actions.",
                },
            )
            self.assertTrue((data_root / "skills" / "marketing-launch" / "SKILL.md").is_file())
            update_status, update_payload = service.handle_action(
                data_root,
                {
                    "action": "update_skill",
                    "id": "marketing-launch",
                    "name": "Marketing Launch",
                    "description": "Use for campaign launch planning.",
                    "content": "Updated launch workflow.",
                    "enabled": False,
                },
            )
            delete_status, delete_payload = service.handle_action(
                data_root,
                {"action": "delete_skill", "skill_id": "marketing-launch"},
            )

            self.assertEqual(create_status, 200)
            self.assertEqual(create_payload["skill"]["id"], "marketing-launch")
            self.assertEqual(update_status, 200)
            self.assertFalse(update_payload["skill"]["enabled"])
            self.assertEqual(delete_status, 200)
            self.assertEqual(delete_payload, {"deleted": True})

    def test_service_rejects_path_traversal_ids(self) -> None:
        service, store = load_skills_backend_modules()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(store.SkillsValidationError):
                service.handle_action(Path(temp) / "skills", {"action": "get_skill", "skill_id": "../escape"})

    def test_service_catalog_only_uses_workspace_skills_data(self) -> None:
        service, store = load_skills_backend_modules()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_root = root / "workspace" / "data" / "skills"
            external_skill = root / "codex" / "skills" / "agent-helper"
            external_skill.mkdir(parents=True)
            external_skill.joinpath("SKILL.md").write_text(
                "---\n"
                "name: Agent Helper\n"
                "description: Use when the installed agent needs helper instructions.\n"
                "---\n\n"
                "# Agent Helper\n\nInstalled skill.\n",
                encoding="utf-8",
            )

            create_status, create_payload = service.handle_action(
                data_root,
                {
                    "action": "create_skill",
                    "id": "agent-helper",
                    "name": "Agent Helper",
                    "description": "Workspace-owned copy.",
                },
            )
            status, payload = service.handle_action(data_root, {"action": "catalog"})

            self.assertEqual(create_status, 200)
            self.assertEqual(create_payload["skill"]["origin"], "workspace")
            self.assertEqual(status, 200)
            self.assertEqual(payload["skills"][0]["id"], "agent-helper")
            self.assertEqual(payload["skills"][0]["origin"], "workspace")
            self.assertTrue(payload["skills"][0]["editable"])
            detail_status, detail_payload = service.handle_action(data_root, {"action": "get_skill", "skill_id": "external-agent-helper"})
            self.assertEqual(detail_status, 404)
            self.assertEqual(detail_payload["error"], "skill_not_found")

    def test_bootstrap_installs_skills_and_exposes_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        self.assertIn("skills", {binding.app_id for binding in bindings})
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "skills" / "state.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "skills" / "skills" / "skills-ops" / "SKILL.md").is_file())

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        skills = list_available_workspace_skills(workspace_id="default", start_path=repo_root)

        self.assertIn("app.skills.maverick_skills_app", [tool.tool_name for tool in tools])
        self.assertIn("app.skills.skills", [command.command_id for command in commands])
        self.assertIn("skills-ops", [skill.skill_id for skill in skills])

    def test_platform_backend_mount_returns_skills_catalog(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        create_status, create_payload = self.invoke(
            app,
            path="/api/apps/skills/backend",
            method="POST",
            body={"action": "create_skill", "id": "sales-call", "name": "Sales Call"},
        )
        catalog_status, catalog_payload = self.invoke(app, path="/api/apps/skills/backend", method="POST", body={"action": "catalog"})

        self.assertEqual(create_status, 200)
        self.assertEqual(create_payload["skill"]["id"], "sales-call")
        self.assertEqual(catalog_status, 200)
        self.assertIn("sales-call", [skill["id"] for skill in catalog_payload["skills"]])

    def test_mcp_and_cli_call_catalog(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        mcp_payload = call_mcp_tool(
            tool_name="app.skills.maverick_skills_app",
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
            command_id="app.skills.skills",
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
        self.assertIn("skills", mcp_payload)
        self.assertIn("skills", cli_payload)


if __name__ == "__main__":
    unittest.main()
