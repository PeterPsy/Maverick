"""Split tests from surface helper module."""

from __future__ import annotations

from dataclasses import replace
import json

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

    def test_app_surface_descriptors_populate_cli_and_mcp_metadata(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps(
                {
                    "commands": {
                        "checklists": {
                            "description": "Manage checklist records through compact app-owned CLI operations.",
                            "argument_schema": {
                                "type": "object",
                                "properties": {
                                    "action": {"type": "string", "enum": ["operations.manifest", "list"]}
                                },
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (app_root / "mcp" / "tool_schemas.json").write_text(
            json.dumps(
                {
                    "tools": {
                        "checklists.list": {
                            "description": "List checklist records compactly.",
                            "input_schema": {
                                "type": "object",
                                "properties": {"limit": {"type": "integer", "maximum": 100}},
                            },
                            "output_schema": {"type": "object", "properties": {"items": {"type": "array"}}},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

        command = next(
            item for item in list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)
            if item.command_id == "app.checklists.checklists"
        )
        tool = next(
            item for item in list_mcp_tools(app_store=store, workspace_id="default", start_path=repo_root)
            if item.tool_name == "app.checklists.checklists.list"
        )

        self.assertEqual(command.description, "Manage checklist records through compact app-owned CLI operations.")
        self.assertEqual(command.argument_schema["properties"]["action"]["enum"], ["operations.manifest", "list"])
        self.assertEqual(tool.description, "List checklist records compactly.")
        self.assertEqual(tool.input_schema["properties"]["limit"]["maximum"], 100)
        self.assertEqual(tool.output_schema["properties"]["items"]["type"], "array")

    def test_invalid_app_surface_descriptors_fall_back_to_generic_metadata(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            '{"commands":{"checklists":{"description":false}}}',
            encoding="utf-8",
        )
        (app_root / "mcp" / "tool_schemas.json").write_text(
            '{"tools":{"checklists.list":{"input_schema":"bad"}}}',
            encoding="utf-8",
        )
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

        command = next(
            item for item in list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)
            if item.command_id == "app.checklists.checklists"
        )
        tool = next(
            item for item in list_mcp_tools(app_store=store, workspace_id="default", start_path=repo_root)
            if item.tool_name == "app.checklists.checklists.list"
        )

        self.assertEqual(command.description, "Workspace app CLI command `checklists` for `checklists`.")
        self.assertEqual(command.argument_schema, {"type": "object"})
        self.assertEqual(tool.description, "App MCP tool exposed by `checklists`.")
        self.assertEqual(tool.input_schema, {"type": "object"})
        self.assertEqual(tool.output_schema, {"type": "object"})

    def test_cli_and_mcp_names_use_local_id_not_mount_id(self) -> None:
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
        binding = install_store_app(
            store,
            source_id=source.source_id,
            workspace_id="default",
            local_app_id="checklists-local",
            start_path=repo_root,
            now=now,
        )
        store.save_workspace_app_binding(replace(binding, mount_app_id="checklists-mount"))

        tools = [tool.tool_name for tool in list_mcp_tools(app_store=store, workspace_id="default", start_path=repo_root)]
        commands = [
            command.command_id
            for command in list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)
        ]

        self.assertIn("app.checklists-local.checklists.list", tools)
        self.assertNotIn("app.checklists-mount.checklists.list", tools)
        self.assertIn("app.checklists-local.checklists", commands)
        self.assertNotIn("app.checklists-mount.checklists", commands)
