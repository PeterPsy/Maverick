"""Split tests from surface helper module."""

from __future__ import annotations

from tests.support.surfaces import *


class TestSurfaceLifecycle(SurfaceTestBase):
    """Focused test slice."""

    def test_disabled_app_surfaces_are_removed_from_platform_hosts(self) -> None:
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
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
        transition_workspace_app_status(store, workspace_id="default", app_id="checklists", target_status="disabled", now=now)

        tools = list_mcp_tools(app_store=store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)

        self.assertNotIn("app.checklists.checklists.list", [tool.tool_name for tool in tools])
        self.assertNotIn("app.checklists.checklists", [command.command_id for command in commands])

    def test_app_tool_names_are_namespaced_to_avoid_cross_app_collisions(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        first_root = repo_root / "apps" / "checklists"
        self.write_app_contract(first_root)
        first_source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(first_root),
            now=now,
        )
        install_store_app(store, source_id=first_source.source_id, workspace_id="default", start_path=repo_root, now=now)

        second_root = repo_root / "apps" / "tasks"
        (second_root / "backend" / "mcp").mkdir(parents=True, exist_ok=True)
        (second_root / "backend" / "cli").mkdir(parents=True, exist_ok=True)
        (second_root / "backend" / "skills" / "task-helper").mkdir(parents=True, exist_ok=True)
        (second_root / "backend" / "mcp" / "server.py").write_text(
            "import json, sys\npayload = json.loads(sys.stdin.read() or '{}')\nprint(json.dumps({'surface': payload.get('surface'), 'tool_name': payload.get('tool_name')}))\n",
            encoding="utf-8",
        )
        (second_root / "backend" / "cli" / "app_cli.py").write_text(
            "import json, sys\npayload = json.loads(sys.stdin.read() or '{}')\nprint(json.dumps({'surface': payload.get('surface'), 'command_id': payload.get('command_id')}))\n",
            encoding="utf-8",
        )
        (second_root / "backend" / "skills" / "task-helper" / "SKILL.md").write_text("# Task Helper\n", encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="tasks",
            name="Tasks",
            version="1.0.0",
            description="Tasks app",
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
        write_app_contract_file(second_root, parsed)
        second_source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(second_root),
            now=now,
        )
        install_store_app(store, source_id=second_source.source_id, workspace_id="default", start_path=repo_root, now=now)

        tools = list_mcp_tools(app_store=store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.checklists.checklists.list", [tool.tool_name for tool in tools])
        self.assertIn("app.tasks.checklists.list", [tool.tool_name for tool in tools])
