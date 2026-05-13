"""Tests for the native Skills app."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.cli.errors import CliInvocationNotAllowedError
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools
from core.skills.service import list_available_workspace_skills
from tests.support.markers import integration_test


SKILLS_BACKEND = Path(__file__).resolve().parents[1] / "backend"


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
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[3] / "apps"
        for app_id in ("base-shell", "chat", "agents", "skills"):
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

    def test_contract_declares_skills_surfaces(self) -> None:
        parsed = parse_app_contract_file(Path(__file__).resolve().parents[1])

        self.assertEqual(parsed.app_id, "skills")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertIn("maverick_skills_app", parsed.contract.capabilities.mcp_tools)
        self.assertIn("skills_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertIn("skills_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["skills", "sync"])
        self.assertIn("skills-ops", parsed.contract.capabilities.skills)
        self.assertIn("skill", {item.entity_type for item in parsed.contract.capabilities.reference_entities})
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "skills")
        self.assertEqual(
            {widget.widget_id for widget in parsed.contract.widgets},
            {"skills-sidebar", "skills-sidebar-footer"},
        )
        app_root = Path(__file__).resolve().parents[1]
        self.assertTrue((app_root / "frontend" / "dist" / "widgets" / "skills-sidebar" / "index.html").is_file())
        self.assertTrue((app_root / "frontend" / "dist" / "widgets" / "skills-sidebar-footer" / "index.html").is_file())

    def test_view_filter_is_available_on_fresh_data_root(self) -> None:
        service, store = load_skills_backend_modules()
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "skills"

            status, payload = service.handle_action(data_root, {"action": "view_filter"})
            state = store.read_state(data_root)

            self.assertEqual(status, 200)
            self.assertEqual(payload["state"]["view_filter"]["mode"], "search")
            self.assertEqual(payload["state"]["view_filter"]["query"], "")
            self.assertEqual(state["view_filter"]["mode"], "search")

    def test_bundled_sdk_skill_sources_do_not_reference_installation_global_paths(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        skill_paths = [
            app_root / "skills" / "maverick-code-skill" / "SKILL.md",
            app_root / "skills" / "maverick-app-creator" / "SKILL.md",
        ]

        for skill_path in skill_paths:
            with self.subTest(skill_path=skill_path):
                content = skill_path.read_text(encoding="utf-8")
                self.assertNotIn("<repo>", content)
                self.assertNotIn("maverick/workspaces/default", content)
                self.assertNotIn("docs/architecture", content)
                self.assertNotIn("core_architecture", content)
                self.assertNotIn("workspace_root_architecture", content)
                self.assertNotIn("app_contract_architecture", content)
                self.assertNotIn("app_sdk_architecture", content)

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

    def test_sync_bundled_skills_ignores_caller_repository_root_payload(self) -> None:
        service, _store = load_skills_backend_modules()
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "skills-data"
            fake_repo = Path(temp) / "attacker-repo"
            fake_repo.mkdir()

            status, payload = service.handle_action(
                data_root,
                {"action": "sync_bundled_skills", "repository_root": str(fake_repo)},
            )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "repository_root_required")

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

    def test_catalog_drops_stale_state_entries_without_skill_files(self) -> None:
        service, store = load_skills_backend_modules()
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "skills"
            store.ensure_data_root(data_root)
            store.write_state(
                data_root,
                [
                    {
                        "id": "stale-skill",
                        "name": "Stale Skill",
                        "description": "Old record without backing files.",
                        "enabled": True,
                    }
                ],
            )

            status, payload = service.handle_action(data_root, {"action": "catalog"})
            rewritten = store.read_state(data_root)

            self.assertEqual(status, 200)
            self.assertEqual(payload["skills"], [])
            self.assertEqual(rewritten["skills"], [])

    def test_catalog_deduplicates_state_entries_and_refreshes_frontmatter(self) -> None:
        service, store = load_skills_backend_modules()
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "skills"
            skill_root = data_root / "skills" / "maverick-app-creator"
            skill_root.mkdir(parents=True)
            skill_root.joinpath("SKILL.md").write_text(
                "---\n"
                "name: maverick-app-creator\n"
                "description: Current clean-slate creator.\n"
                "---\n\n"
                "# Maverick App Creator\n\nCreate a new app.\n",
                encoding="utf-8",
            )
            store.ensure_data_root(data_root)
            store.write_state(
                data_root,
                [
                    {
                        "id": "maverick-app-creator",
                        "name": "maverick-app-creator",
                        "description": "Old duplicate description.",
                        "enabled": True,
                    },
                    {
                        "id": "maverick-app-creator",
                        "name": "maverick-app-creator",
                        "description": "Another stale duplicate.",
                        "enabled": True,
                    },
                    {
                        "id": "removed-bundle",
                        "name": "removed-bundle",
                        "description": "Deleted bundle.",
                        "enabled": True,
                    },
                ],
            )

            status, payload = service.handle_action(data_root, {"action": "catalog"})
            rewritten = store.read_state(data_root)

            self.assertEqual(status, 200)
            self.assertEqual([item["id"] for item in payload["skills"]], ["maverick-app-creator"])
            self.assertEqual(payload["skills"][0]["description"], "Current clean-slate creator.")
            self.assertEqual([item["id"] for item in rewritten["skills"]], ["maverick-app-creator"])

    @integration_test("skills platform integration suite; run with scripts/test_suite.py --level integration")
    def test_bootstrap_installs_skills_and_exposes_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        self.assertIn("skills", {binding.app_id for binding in bindings})
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "skills" / "state.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "skills" / "skills" / "skills-ops" / "SKILL.md").is_file())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "skills" / "skills" / "generate-image" / "SKILL.md").is_file())

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        skills = list_available_workspace_skills(workspace_id="default", start_path=repo_root)

        self.assertIn("app.skills.maverick_skills_app", [tool.tool_name for tool in tools])
        self.assertIn("app.skills.skills", [command.command_id for command in commands])
        self.assertIn("skills-ops", [skill.skill_id for skill in skills])
        self.assertIn("generate-image", [skill.skill_id for skill in skills])

    @integration_test("skills platform integration suite; run with scripts/test_suite.py --level integration")
    def test_platform_backend_mount_returns_skills_catalog(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        create_status, create_payload, _create_headers = self.invoke(
            app,
            path="/api/apps/skills/backend",
            method="POST",
            body={"action": "create_skill", "id": "sales-call", "name": "Sales Call"},
            cookie=cookie,
        )
        catalog_status, catalog_payload, _headers = self.invoke(
            app,
            path="/api/apps/skills/backend",
            method="POST",
            body={"action": "catalog"},
            cookie=cookie,
        )

        self.assertEqual(create_status, 200)
        self.assertEqual(create_payload["skill"]["id"], "sales-call")
        self.assertEqual(catalog_status, 200)
        self.assertIn("sales-call", [skill["id"] for skill in catalog_payload["skills"]])

    @integration_test("skills platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("skills platform integration suite; run with scripts/test_suite.py --level integration")
    def test_admin_sync_command_repairs_catalog_and_seeds_bundled_skills(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        data_root = repo_root / "workspaces" / "default" / "data" / "skills"
        generate_image_root = data_root / "skills" / "generate-image"
        shutil.rmtree(generate_image_root)
        state_payload = json.loads((data_root / "state.json").read_text(encoding="utf-8"))
        state_payload["skills"].append(
            {
                "id": "stale-skill",
                "name": "Stale Skill",
                "description": "Old record without backing files.",
                "enabled": True,
            }
        )
        (data_root / "state.json").write_text(json.dumps(state_payload, indent=2) + "\n", encoding="utf-8")

        result = run_core_cli_command(
            command_id="app.skills.sync",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="agent-1",
                effective_mode="sandbox",
                platform_role="admin",
            ),
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        rebuilt_state = json.loads((data_root / "state.json").read_text(encoding="utf-8"))
        rebuilt_ids = {item["id"] for item in rebuilt_state["skills"]}

        self.assertEqual(result["status_code"], 200)
        self.assertIn("generate-image", result["seeded_skill_ids"])
        self.assertIn("generate-image", rebuilt_ids)
        self.assertNotIn("stale-skill", rebuilt_ids)

    @integration_test("skills platform integration suite; run with scripts/test_suite.py --level integration")
    def test_sync_command_is_blocked_for_non_admin_users(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
            command_id="app.skills.sync",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="agent-1",
                effective_mode="sandbox",
                platform_role="member",
            ),
                app_store=state.app_store,
                workspace_id="default",
                start_path=repo_root,
            )


if __name__ == "__main__":
    unittest.main()
