"""Split tests from surface helper module."""

from __future__ import annotations

import json
from types import SimpleNamespace

from core.app_sdk.cli import run_cli_json
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.errors import RuntimeSessionNotFoundError
from core.secrets.errors import SecretPolicyError
from core.secrets.service import build_secret_ref, create_platform_secret, grant_app_secret_use
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.surfaces import *


def _inter_agent_run_payload(*, run_id: str, root_session_id: str) -> dict:
    return {
        "run_id": run_id,
        "thread_id": root_session_id,
        "root_runtime_session_id": root_session_id,
        "source_app_id": "chat",
        "mode": "manager_tools",
        "idempotency_key": run_id,
        "participants": [
            {
                "participant_id": "orchestrator",
                "kind": "orchestrator",
                "execution_mode": "root_orchestrator",
                "label": "Orchestrator",
            },
            {
                "participant_id": "researcher",
                "kind": "agent",
                "execution_mode": "child_runtime_session",
                "label": "Researcher",
                "agent_type_id": "research-agent",
                "agent_snapshot": {
                    "agent_type_id": "research-agent",
                    "label": "Researcher",
                    "system_prompt": "Research only.",
                    "skill_ids": ["storage"],
                    "skill_catalog_app_id": "skills",
                },
            },
        ],
        "budget": {
            "max_participants": 3,
            "max_concurrent_participants": 2,
            "max_total_turns": 4,
            "max_turns_per_participant": 2,
        },
    }


class TestMcpCliSurfaces(SurfaceTestBase):
    """Focused test slice."""

    def test_developer_context_surfaces_are_listed_for_workspace_agents(self) -> None:
        repo_root = self.make_repo_root()

        commands = list_core_cli_commands(workspace_id="default", start_path=repo_root)
        tools = list_mcp_tools(workspace_id="default", start_path=repo_root)

        self.assertIn("developer-context.list", [command.command_id for command in commands])
        self.assertIn("developer-context.read", [command.command_id for command in commands])
        self.assertIn("core.persistence.status", [command.command_id for command in commands])
        self.assertIn("developer-context.list", [tool.tool_name for tool in tools])
        self.assertIn("developer-context.read", [tool.tool_name for tool in tools])
        self.assertIn("core.persistence.status", [tool.tool_name for tool in tools])

    def test_inter_agent_cli_and_mcp_surfaces_spawn_hidden_runtime_sessions(self) -> None:
        repo_root = self.make_repo_root()
        app_store = self.make_app_store()
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        runtime_store = self.make_runtime_store()
        inter_agent_store = build_inter_agent_document_store(start_path=repo_root)
        create_runtime_session(
            runtime_store,
            session_id="root-cli",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        create_runtime_session(
            runtime_store,
            session_id="root-mcp",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        cli_context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
            user_id="operator",
        )
        mcp_context = McpInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
            user_id="operator",
        )

        commands = list_core_cli_commands(
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
        )
        tools = list_mcp_tools(
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_create = run_core_cli_command(
            command_id="inter-agent.runs.create",
            context=cli_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="cli-run", root_session_id="root-cli"),
        )
        cli_spawn = run_core_cli_command(
            command_id="inter-agent.participants.spawn",
            context=cli_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"run_id": "cli-run", "participant_id": "researcher", "child_session_id": "cli-child"},
        )
        mcp_create = call_mcp_tool(
            tool_name="inter_agent_run_create",
            context=mcp_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="mcp-run", root_session_id="root-mcp"),
        )
        mcp_spawn = call_mcp_tool(
            tool_name="inter_agent_participant_spawn",
            context=mcp_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"run_id": "mcp-run", "participant_id": "researcher", "child_session_id": "mcp-child"},
        )
        cli_child_skill_ids = runtime_store.get_session("cli-child").skill_ids
        mcp_wait = call_mcp_tool(
            tool_name="inter_agent_wait",
            context=mcp_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"run_id": "mcp-run", "timeout_seconds": 0},
        )
        cli_close = run_core_cli_command(
            command_id="inter-agent.runs.close",
            context=cli_context,
            app_store=app_store,
            workspace_store=workspace_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"run_id": "cli-run", "reason": "test-close"},
        )

        command_ids = {command.command_id for command in commands}
        tool_names = {tool.tool_name for tool in tools}
        self.assertTrue(
            {
                "inter-agent.runs.create",
                "inter-agent.participants.spawn",
                "inter-agent.messages.send",
                "inter-agent.runs.wait",
                "inter-agent.runs.interrupt",
                "inter-agent.runs.resume",
                "inter-agent.runs.close",
            }.issubset(command_ids)
        )
        self.assertTrue(
            {
                "inter_agent_run_create",
                "inter_agent_participant_spawn",
                "inter_agent_message_send",
                "inter_agent_wait",
                "inter_agent_interrupt",
                "inter_agent_resume",
                "inter_agent_close",
            }.issubset(tool_names)
        )
        self.assertEqual(cli_create["run"]["run_id"], "cli-run")
        self.assertEqual(cli_spawn["runtime_session"]["session_kind"], "inter_agent_participant")
        self.assertEqual(cli_spawn["runtime_session"]["thread_visibility"], "hidden")
        self.assertEqual(cli_child_skill_ids, ["storage"])
        self.assertEqual(mcp_create["run"]["run_id"], "mcp-run")
        self.assertEqual(mcp_spawn["runtime_session"]["session_kind"], "inter_agent_participant")
        self.assertEqual(mcp_spawn["runtime_session"]["thread_visibility"], "hidden")
        self.assertEqual(mcp_wait["run"]["run_id"], "mcp-run")
        self.assertEqual(cli_close["run"]["status"], "cancelled")
        with self.assertRaises(RuntimeSessionNotFoundError):
            runtime_store.get_session("cli-child")

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
        self.assertEqual(app_result["effective_mode"], "full-access")
        self.assertIsNone(app_result["agent_id"])
        self.assertIsNone(app_result["runtime_session_id"])
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

    def test_cli_registry_allows_core_operator_only_recovery_and_agents_can_list_providers(self) -> None:
        store = self.make_app_store()
        workspace_store = self.make_workspace_store()
        provider_store = self.make_provider_store()
        ensure_default_workspace_record(workspace_store)
        register_builtin_providers(provider_store)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
        context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        commands = list_core_cli_commands(
            app_store=store,
            workspace_store=workspace_store,
            provider_store=provider_store,
            workspace_id="default",
            context=context,
            start_path=repo_root,
        )
        provider_result = run_core_cli_command(
            command_id="core.providers.list",
            context=context,
            provider_store=provider_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(["core.identity.reset-admin-password"], [command.command_id for command in commands if command.invocation_policy.operator_only])
        self.assertEqual(provider_result["providers"][0]["provider_id"], "codex")

    def test_app_cli_policy_rejects_operator_only_true(self) -> None:
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

        with self.assertRaises(ValueError):
            list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)

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
        self.assertEqual(result["agent_id"], "agent-1")
        self.assertEqual(result["effective_mode"], "sandbox")
        self.assertIsNone(result["runtime_session_id"])
        self.assertTrue(result["workspace_root"].endswith("/workspaces/default"))
        self.assertTrue(result["data_root"].endswith("/workspaces/default/data/checklists"))
        self.assertEqual(result["python"], sys.executable)

    def test_full_access_only_app_cli_and_mcp_discovery_uses_full_access_policy(self) -> None:
        store = self.make_app_store()
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root, workspace_modes=["full-access"])
        source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)

        commands = list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)
        tools = list_mcp_tools(app_store=store, workspace_id="default", start_path=repo_root)
        command = next(command for command in commands if command.command_id == "app.checklists.checklists")
        tool = next(tool for tool in tools if tool.tool_name == "app.checklists.checklists.list")
        sandbox_cli_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )
        sandbox_mcp_context = McpInvocationContext(**sandbox_cli_context.__dict__)

        self.assertFalse(command.invocation_policy.sandbox_agent_allowed)
        self.assertTrue(command.invocation_policy.requires_full_access)
        self.assertFalse(tool.invocation_policy.sandbox_agent_allowed)
        self.assertTrue(tool.invocation_policy.requires_full_access)
        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="app.checklists.checklists",
                context=sandbox_cli_context,
                app_store=store,
                workspace_id="default",
                start_path=repo_root,
            )
        with self.assertRaises(McpInvocationNotAllowedError):
            call_mcp_tool(
                tool_name="app.checklists.checklists.list",
                context=sandbox_mcp_context,
                app_store=store,
                workspace_id="default",
                start_path=repo_root,
            )

    def test_app_scoped_inspect_reports_full_access_policy_from_contract(self) -> None:
        store = self.make_app_store()
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root, workspace_modes=["full-access"])
        source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
        state = SimpleNamespace(
            repository_root=repo_root,
            app_store=store,
            identity_store=None,
            workspace_store=None,
            runtime_store=None,
            provider_store=None,
            secret_store=None,
            recovery_store=None,
            observability_store=None,
            app_event_bus=None,
        )

        cli_result = run_cli_json(
            ["app", "checklists", "cli", "inspect", "checklists", "--json"],
            state=state,
            repository_root=repo_root,
        )
        mcp_result = run_cli_json(
            ["app", "checklists", "mcp", "inspect", "checklists.list", "--json"],
            state=state,
            repository_root=repo_root,
        )

        self.assertEqual(
            cli_result["command"]["invocation_policy"],
            {
                "operator_only": False,
                "required_platform_role": None,
                "sandbox_agent_allowed": False,
                "requires_workspace_context": True,
                "requires_full_access": True,
            },
        )
        self.assertEqual(
            mcp_result["tool"]["invocation_policy"],
            {
                "operator_only": False,
                "sandbox_agent_allowed": False,
                "requires_workspace_context": True,
                "requires_full_access": True,
            },
        )

    def test_app_cli_policy_cannot_loosen_full_access_only_contract(self) -> None:
        store = self.make_app_store()
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root, workspace_modes=["full-access"])
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_policies.json").write_text(
            json.dumps(
                {
                    "commands": {
                        "checklists": {
                            "sandbox_agent_allowed": True,
                            "requires_full_access": False,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)

        commands = list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)
        command = next(command for command in commands if command.command_id == "app.checklists.checklists")

        self.assertFalse(command.invocation_policy.sandbox_agent_allowed)
        self.assertTrue(command.invocation_policy.requires_full_access)

    def test_app_cli_and_mcp_receive_app_secrets_from_grants(self) -> None:
        store = self.make_app_store()
        workspace_store = self.make_workspace_store()
        secret_store = SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"test-key",
        )
        ensure_default_workspace_record(workspace_store)
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root, secret_read=["api-token", "webhook-token"])
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps({"commands": {"checklists": {"required_secrets": ["api-token"]}}}),
            encoding="utf-8",
        )
        (app_root / "mcp" / "tool_schemas.json").write_text(
            json.dumps({"tools": {"checklists.list": {"required_secrets": ["webhook-token"]}}}),
            encoding="utf-8",
        )
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
        secret = create_platform_secret(secret_store, label="API Token", raw_value="grant-secret", alias="api-token")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="checklists",
            logical_name="api-token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
        )
        webhook_secret = create_platform_secret(secret_store, label="Webhook Token", raw_value="webhook-secret", alias="webhook-token")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="checklists",
            logical_name="webhook-token",
            secret_ref=build_secret_ref(alias=webhook_secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
        )
        cli_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
            runtime_session_id="sess-cli",
            user_id="user-1",
        )
        mcp_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
            runtime_session_id="sess-mcp",
            user_id="user-1",
        )

        cli_result = run_core_cli_command(
            command_id="app.checklists.checklists",
            context=cli_context,
            app_store=store,
            workspace_store=workspace_store,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"limit": 5},
        )
        mcp_result = call_mcp_tool(
            tool_name="app.checklists.checklists.list",
            context=mcp_context,
            app_store=store,
            workspace_store=workspace_store,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"limit": 5},
        )

        self.assertEqual(cli_result["app_secrets"], {"api-token": "grant-secret"})
        self.assertEqual(cli_result["app_secret_errors"], [])
        self.assertEqual(mcp_result["app_secrets"], {"webhook-token": "webhook-secret"})
        self.assertEqual(mcp_result["app_secret_errors"], [])

    def test_app_secret_delivery_uses_command_and_tool_targets(self) -> None:
        store = self.make_app_store()
        workspace_store = self.make_workspace_store()
        secret_store = SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"test-key",
        )
        ensure_default_workspace_record(workspace_store)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root, secret_read=["api-token"])
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps({"commands": {"checklists": {"required_secrets": ["api-token"]}}}),
            encoding="utf-8",
        )
        (app_root / "mcp" / "tool_schemas.json").write_text(
            json.dumps({"tools": {"checklists.list": {"required_secrets": ["api-token"]}}}),
            encoding="utf-8",
        )
        source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
        secret = create_platform_secret(secret_store, label="API Token", raw_value="grant-secret", alias="api-token")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="checklists",
            logical_name="api-token",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/cli/checklists"],
        )
        context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        cli_result = run_core_cli_command(
            command_id="app.checklists.checklists",
            context=context,
            app_store=store,
            workspace_store=workspace_store,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"limit": 5},
        )
        with self.assertRaises(SecretPolicyError):
            call_mcp_tool(
                tool_name="app.checklists.checklists.list",
                context=McpInvocationContext(**context.__dict__),
                app_store=store,
                workspace_store=workspace_store,
                secret_store=secret_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={"limit": 5},
            )

        self.assertEqual(cli_result["app_secrets"], {"api-token": "grant-secret"})

    def test_app_cli_and_mcp_secret_selectors_scope_resource_grants(self) -> None:
        store = self.make_app_store()
        workspace_store = self.make_workspace_store()
        secret_store = SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"test-key",
        )
        ensure_default_workspace_record(workspace_store)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root, secret_read=["api-token"])
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        selector = {
            "required_secrets": ["api-token"],
            "resource_type": "mail_connection",
            "resource_id_argument": "connection_id",
        }
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps({"commands": {"checklists": {"secret_selectors": [selector]}}}),
            encoding="utf-8",
        )
        (app_root / "mcp" / "tool_schemas.json").write_text(
            json.dumps({"tools": {"checklists.list": {"secret_selectors": [selector]}}}),
            encoding="utf-8",
        )
        source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
        first = create_platform_secret(secret_store, label="First", raw_value="first-secret", alias="first-secret")
        second = create_platform_secret(secret_store, label="Second", raw_value="second-secret", alias="second-secret")
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="checklists",
            logical_name="api-token",
            secret_ref=build_secret_ref(alias=first.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            resource_type="mail_connection",
            resource_id="conn_1",
        )
        grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="checklists",
            logical_name="api-token",
            secret_ref=build_secret_ref(alias=second.alias),
            actions=["app.backend"],
            target_patterns=["maverick://app.backend/*"],
            resource_type="mail_connection",
            resource_id="conn_2",
        )
        context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        cli_result = run_core_cli_command(
            command_id="app.checklists.checklists",
            context=context,
            app_store=store,
            workspace_store=workspace_store,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"connection_id": "conn_2"},
        )
        mcp_result = call_mcp_tool(
            tool_name="app.checklists.checklists.list",
            context=McpInvocationContext(**context.__dict__),
            app_store=store,
            workspace_store=workspace_store,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"connection_id": "conn_1"},
        )

        self.assertEqual(cli_result["app_secrets"], {"api-token": "second-secret"})
        self.assertEqual(mcp_result["app_secrets"], {"api-token": "first-secret"})

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
