"""Split tests from tests/test_phase9_surfaces.py."""

from __future__ import annotations

from tests.phase9_surfaces_helpers import *


class TestPhase9McpCliSurfaces(Phase9SurfacesBase):
    """Focused test slice."""

    def test_developer_context_surfaces_are_listed_for_workspace_agents(self) -> None:
        repo_root = self.make_repo_root()

        commands = list_core_cli_commands(workspace_id="default", start_path=repo_root)
        tools = list_mcp_tools(workspace_id="default", start_path=repo_root)

        self.assertIn("developer-context.list", [command.command_id for command in commands])
        self.assertIn("developer-context.read", [command.command_id for command in commands])
        self.assertIn("developer-context.list", [tool.tool_name for tool in tools])
        self.assertIn("developer-context.read", [tool.tool_name for tool in tools])

    def test_developer_context_cli_and_mcp_return_canonical_document_text(self) -> None:
        repo_root = self.make_repo_root()
        (repo_root / "AGENTS.md").write_text("Working agreement body.\n", encoding="utf-8")
        (repo_root / "docs" / "architecture" / "core_architecture.md").write_text("# Core\n\nCanonical core architecture.\n", encoding="utf-8")
        (repo_root / "docs" / "architecture" / "workspace_root_architecture.md").write_text("# Workspace\n\nCanonical workspace architecture.\n", encoding="utf-8")
        (repo_root / "docs" / "architecture" / "app_contract_architecture.md").write_text("# App Contract\n\nCanonical app contract architecture.\n", encoding="utf-8")
        sandbox_cli_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )
        sandbox_mcp_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        cli_list = run_core_cli_command(
            command_id="developer-context.list",
            context=sandbox_cli_context,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_read = run_core_cli_command(
            command_id="developer-context.read",
            context=sandbox_cli_context,
            workspace_id="default",
            start_path=repo_root,
            arguments={"doc_id": "core_architecture"},
        )
        mcp_read = call_mcp_tool(
            tool_name="developer-context.read",
            context=sandbox_mcp_context,
            workspace_id="default",
            start_path=repo_root,
            arguments={"doc_id": "agents_working_agreement"},
        )

        self.assertEqual([item["doc_id"] for item in cli_list["items"]], [
            "agents_working_agreement",
            "core_architecture",
            "workspace_root_architecture",
            "app_contract_architecture",
        ])
        self.assertEqual(cli_read["doc_id"], "core_architecture")
        self.assertEqual(cli_read["source_path"], "docs/architecture/core_architecture.md")
        self.assertIn("Canonical core architecture.", cli_read["content"])
        self.assertEqual(mcp_read["doc_id"], "agents_working_agreement")
        self.assertEqual(mcp_read["source_path"], "AGENTS.md")
        self.assertIn("Working agreement body.", mcp_read["content"])

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
