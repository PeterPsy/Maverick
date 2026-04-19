"""Split tests from tests/test_phase9_surfaces.py."""

from __future__ import annotations

from tests.phase9_surfaces_helpers import *


class TestPhase9McpCliSurfaces(Phase9SurfacesBase):
    """Focused test slice."""

    def test_workspace_mcp_surface_merges_core_and_enabled_app_tools(self) -> None:
        store = self.make_app_store()
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        provider_store = self.make_provider_store()
        register_builtin_providers(provider_store)
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

        tools = list_mcp_tools(app_store=store, workspace_id="default", start_path=repo_root)
        surface = build_workspace_mcp_surface(
            app_store=store,
            workspace_store=workspace_store,
            provider_store=provider_store,
            workspace_id="default",
            start_path=repo_root,
            transport="http",
        )

        self.assertIn("core.runtime.status", [tool.tool_name for tool in tools])
        self.assertIn("app.checklists.checklists.list", [tool.tool_name for tool in tools])
        self.assertEqual(surface.transport, "http")
        self.assertEqual(surface.manifest.tool_count, len(tools))
        operator_context = McpInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )
        app_result = surface.call_tool("app.checklists.checklists.list", {"limit": 5}, context=operator_context)
        core_result = surface.call_tool("core.workspaces.list", context=operator_context)
        self.assertEqual(app_result["surface"], "mcp")
        self.assertEqual(app_result["tool_name"], "checklists.list")
        self.assertTrue(app_result["workspace_root"].endswith("/workspaces/default"))
        self.assertTrue(app_result["data_root"].endswith("/workspaces/default/data/checklists"))
        self.assertEqual(core_result["items"][0]["workspace_id"], "default")

    def test_mcp_policy_blocks_operator_only_tools_for_sandboxed_agents(self) -> None:
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        provider_store = self.make_provider_store()
        register_builtin_providers(provider_store)
        repo_root = self.make_repo_root()
        surface = build_workspace_mcp_surface(
            workspace_store=workspace_store,
            provider_store=provider_store,
            workspace_id="default",
            start_path=repo_root,
        )
        sandbox_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        with self.assertRaises(McpInvocationNotAllowedError):
            surface.call_tool("core.providers.list", context=sandbox_context)

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
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
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
            workspace_store=workspace_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"limit": 5},
        )

        self.assertIn("app.checklists.checklists", [command.command_id for command in commands])
        self.assertEqual(result["workspace_id"], "default")
        self.assertEqual(result["surface"], "cli")
        self.assertEqual(result["command_id"], "app.checklists.checklists")
        self.assertTrue(result["workspace_root"].endswith("/workspaces/default"))
        self.assertTrue(result["data_root"].endswith("/workspaces/default/data/checklists"))
        self.assertEqual(result["python"], sys.executable)

    def test_core_cli_commands_return_operational_data_when_stores_are_available(self) -> None:
        workspace_store = self.make_workspace_store()
        provider_store = self.make_provider_store()
        runtime_store = self.make_runtime_store()
        ensure_default_workspace_record(workspace_store)
        register_builtin_providers(provider_store)
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        operator_context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )

        workspace_result = run_core_cli_command(
            command_id="core.workspaces.current",
            context=operator_context,
            workspace_store=workspace_store,
            workspace_id="default",
        )
        runtime_result = run_core_cli_command(
            command_id="core.runtime.status",
            context=operator_context,
            runtime_store=runtime_store,
            workspace_id="default",
        )
        provider_result = run_core_cli_command(
            command_id="core.providers.list",
            context=operator_context,
            provider_store=provider_store,
        )

        self.assertEqual(workspace_result["workspace"]["workspace_id"], "default")
        self.assertEqual(runtime_result["sessions"][0]["session_id"], "sess-1")
        self.assertEqual(provider_result["providers"][0]["provider_id"], "codex")
