"""Regression coverage for per-app CLI and MCP fault isolation."""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

from core.app_sdk.cli import run_cli_json
from tests.support.surfaces import *


class AppSurfaceFaultIsolationTest(SurfaceTestBase):
    def test_workspace_surfaces_skip_enabled_app_with_missing_source(self) -> None:
        store = self.make_app_store()
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)

        healthy_root = repo_root / "apps" / "checklists"
        self.write_app_contract(healthy_root)
        healthy_source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(healthy_root),
            now=now,
        )
        install_store_app(
            store,
            source_id=healthy_source.source_id,
            workspace_id="default",
            start_path=repo_root,
            now=now,
        )

        missing_root = repo_root / "apps" / "unavailable-app"
        write_app_contract_file(
            missing_root,
            build_parsed_app_contract(
                app_id="unavailable-app",
                name="Unavailable App",
                version="1.0.0",
                description="App source removed after installation.",
                publisher="maverick",
                contract=build_app_contract(),
            ),
        )
        missing_source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(missing_root),
            now=now,
        )
        install_store_app(
            store,
            source_id=missing_source.source_id,
            workspace_id="default",
            start_path=repo_root,
            now=now,
        )
        shutil.rmtree(missing_root)

        state = SimpleNamespace(
            repository_root=repo_root,
            app_store=store,
            identity_store=None,
            workspace_store=workspace_store,
            runtime_store=None,
            provider_store=None,
            secret_store=None,
            recovery_store=None,
            observability_store=None,
            app_event_bus=None,
        )

        commands = list_core_cli_commands(
            app_store=store,
            workspace_store=workspace_store,
            workspace_id="default",
            start_path=repo_root,
        )
        tools = list_mcp_tools(
            app_store=store,
            workspace_store=workspace_store,
            workspace_id="default",
            start_path=repo_root,
        )
        apps = run_cli_json(["apps", "list", "--json"], state=state, repository_root=repo_root)
        app_cli = run_cli_json(
            ["app", "checklists", "cli", "list", "--json"],
            state=state,
            repository_root=repo_root,
        )
        app_mcp = run_cli_json(
            ["app", "checklists", "mcp", "list", "--json"],
            state=state,
            repository_root=repo_root,
        )

        self.assertIn("developer-context.list", [command.command_id for command in commands])
        self.assertIn("app.checklists.checklists", [command.command_id for command in commands])
        self.assertIn("app.checklists.checklists.list", [tool.tool_name for tool in tools])
        self.assertEqual([item["app_id"] for item in apps["apps"]], ["checklists"])
        self.assertEqual([item["name"] for item in app_cli["commands"]], ["checklists"])
        self.assertEqual([item["name"] for item in app_mcp["tools"]], ["checklists.list"])

    def test_cli_policy_error_skips_only_invalid_app_commands(self) -> None:
        store = self.make_app_store()
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        policy_path = app_root / "cli" / "command_policies.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(
            json.dumps({"commands": {"checklists": {"operator_only": True}}}),
            encoding="utf-8",
        )
        source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)

        with self.assertLogs("core.cli.registry_builder", level="ERROR"):
            commands = list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)

        command_ids = {command.command_id for command in commands}
        self.assertIn("developer-context.list", command_ids)
        self.assertNotIn("app.checklists.checklists", command_ids)


if __name__ == "__main__":
    unittest.main()
