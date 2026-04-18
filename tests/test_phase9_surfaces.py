"""Tests for Phase 9 MCP, CLI, and skills surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from core.apps.contracts import (
    build_app_capabilities,
    build_app_contract,
    build_app_entrypoints,
    build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.service import install_external_app, register_app_source_from_contract
from core.apps.store import AppCollections, MongoAppStore
from core.cli.errors import CliInvocationNotAllowedError
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.service import build_workspace_mcp_surface, list_mcp_tools
from core.providers.service import prepare_runtime_skills, register_builtin_providers
from core.providers.store import MongoProviderStore, ProviderCollections
from core.runtime.service import create_runtime_session
from core.runtime.store import MongoRuntimeStore, RuntimeCollections
from core.skills.service import list_visible_platform_skills


class FakeCollection:
    """Small in-memory collection for control-plane store tests."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None

    def find(self, query: dict) -> list[dict]:
        return [dict(document) for document in self.documents if all(document.get(key) == value for key, value in query.items())]

    def update_one(self, query: dict, update: dict, *, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents[index] = {**document, **payload}
                return
        if upsert:
            self.documents.append({**query, **payload})

    def delete_one(self, query: dict) -> None:
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents.pop(index)
                return


class Phase9SurfacesTestCase(unittest.TestCase):
    """Verify platform-managed MCP, CLI, and skills surfaces."""

    def make_app_store(self) -> MongoAppStore:
        return MongoAppStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
            )
        )

    def make_provider_store(self) -> MongoProviderStore:
        return MongoProviderStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )

    def make_runtime_store(self) -> MongoRuntimeStore:
        return MongoRuntimeStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
            )
        )

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "local-skills", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        (repo_root / "local-skills" / "core-ops").mkdir(parents=True, exist_ok=True)
        (repo_root / "local-skills" / "core-ops" / "SKILL.md").write_text("# Core Ops\n", encoding="utf-8")
        return repo_root

    def write_app_contract(self, app_root: Path) -> None:
        (app_root / "backend" / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "skills" / "task-helper").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "mcp" / "server.py").write_text("print('mcp')\n", encoding="utf-8")
        (app_root / "backend" / "cli" / "app_cli.py").write_text("print('cli')\n", encoding="utf-8")
        (app_root / "backend" / "skills" / "task-helper" / "SKILL.md").write_text("# Task Helper\n", encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="checklists",
            name="Checklists",
            version="1.0.0",
            description="Checklist app",
            publisher="maverick",
            contract=build_app_contract(
                capabilities=build_app_capabilities(
                    mcp_tools=["checklists.list"],
                    cli_commands=["checklists"],
                    skills=["task-helper"],
                    views=[],
                ),
                entrypoints=build_app_entrypoints(
                    mcp="backend/mcp/server.py",
                    cli="backend/cli/app_cli.py",
                    skills_root="backend/skills",
                ),
            ),
        )
        write_app_contract_file(app_root, parsed)

    def test_workspace_mcp_surface_merges_core_and_enabled_app_tools(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_external_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

        tools = list_mcp_tools(app_store=store, workspace_id="default", start_path=repo_root)
        surface = build_workspace_mcp_surface(app_store=store, workspace_id="default", start_path=repo_root, transport="http")

        self.assertIn("core.runtime.status", [tool.tool_name for tool in tools])
        self.assertIn("checklists.list", [tool.tool_name for tool in tools])
        self.assertEqual(surface.transport, "http")
        self.assertEqual(surface.manifest.tool_count, len(tools))

    def test_cli_policy_blocks_operator_only_commands_for_sandboxed_agents(self) -> None:
        context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(command_id="core.providers.list", context=context, workspace_id="default")

    def test_cli_registry_exposes_enabled_app_commands_with_workspace_safe_policy(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_external_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
        context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        commands = list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)
        result = run_core_cli_command(
            command_id="app.checklists.checklists",
            context=context,
            app_store=store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"limit": 5},
        )

        self.assertIn("app.checklists.checklists", [command.command_id for command in commands])
        self.assertEqual(result["workspace_id"], "default")
        self.assertTrue(result["entrypoint_path"].endswith("backend/cli/app_cli.py"))

    def test_visible_skills_merge_core_and_enabled_app_skills(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_external_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

        skills = list_visible_platform_skills(app_store=store, workspace_id="default", start_path=repo_root)

        self.assertIn("core-ops", [skill.skill_id for skill in skills])
        self.assertIn("task-helper", [skill.skill_id for skill in skills])

    def test_provider_adapter_materializes_skills_into_provider_specific_runtime_home(self) -> None:
        app_store = self.make_app_store()
        provider_store = self.make_provider_store()
        runtime_store = self.make_runtime_store()
        register_builtin_providers(provider_store)
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        source = register_app_source_from_contract(
            app_store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_external_app(app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
            now=now,
            requested_mode="sandbox",
            start_path=repo_root,
        )
        skills = list_visible_platform_skills(app_store=app_store, workspace_id="default", start_path=repo_root)

        materializations = prepare_runtime_skills(provider_store, session=session, skills=skills, codex_command="/bin/echo")

        target_roots = [Path(item.target_root) for item in materializations]
        self.assertTrue(any(path.name == "core-ops" for path in target_roots))
        self.assertTrue(any(path.name == "task-helper" for path in target_roots))
        for path in target_roots:
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.parent.name, "skills")
            self.assertEqual(path.parent.parent.name, "codex-home")


if __name__ == "__main__":
    unittest.main()
