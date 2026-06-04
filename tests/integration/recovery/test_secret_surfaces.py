"""Split tests from observability helper module."""

from __future__ import annotations

import json
from unittest.mock import patch

from core.cli.errors import CliInvocationNotAllowedError
from core.cli.service import list_core_cli_commands
from core.mcp.errors import McpInvocationNotAllowedError
from core.mcp.service import list_mcp_tools
from core.secrets.app_delivery import app_secret_target
from core.secrets.errors import SecretPolicyError
from core.secrets.service import grant_app_secret_use
from core.workspaces.service import ensure_workspace_membership
from tests.support.repo import write_synthetic_platform_app
from tests.support.observability import *


class TestSecretRecoverySurfaces(ObservabilityTestBase):
    """Focused test slice."""

    def enable_secret_consumer_app(
        self,
        repo_root: Path,
        app_store: AppDocumentStore,
        *,
        app_id: str = "browser",
        secret_read: list[str],
        backend: bool = True,
        cli_commands: list[str] | None = None,
        mcp_tools: list[str] | None = None,
    ) -> Path:
        app_root = write_synthetic_platform_app(
            repo_root,
            app_id=app_id,
            backend=backend,
            cli_commands=cli_commands,
            mcp_tools=mcp_tools,
        )
        contract_path = app_root / "app_contract.json"
        contract_payload = json.loads(contract_path.read_text(encoding="utf-8"))
        contract_payload["permissions"]["secrets"]["read"] = secret_read
        if cli_commands:
            (app_root / "cli").mkdir(parents=True, exist_ok=True)
            (app_root / "cli" / "app_cli.py").write_text(
                "import json, sys\njson.dump({'ok': True}, sys.stdout)\n",
                encoding="utf-8",
            )
            contract_payload["entrypoints"]["cli"] = "cli/app_cli.py"
        if mcp_tools:
            (app_root / "mcp").mkdir(parents=True, exist_ok=True)
            (app_root / "mcp" / "server.py").write_text(
                "import json, sys\njson.dump({'ok': True}, sys.stdout)\n",
                encoding="utf-8",
            )
            contract_payload["entrypoints"]["mcp"] = "mcp/server.py"
        contract_path.write_text(json.dumps(contract_payload, indent=2), encoding="utf-8")
        source = register_app_source_from_contract(
            app_store,
            source_kind="platform",
            source_path=str(app_root),
            source_id=f"platform:{app_id}",
        )
        install_store_app(
            app_store,
            source_id=source.source_id,
            workspace_id="default",
            enabled=True,
            start_path=repo_root,
        )
        return app_root

    def assert_payload_has_no_secret_material(self, payload: object, *raw_values: str) -> None:
        encoded = json.dumps(payload, sort_keys=True, default=str)
        for raw_value in raw_values:
            self.assertNotIn(raw_value, encoded)
        if isinstance(payload, dict):
            self.assertNotIn("raw_value", payload)
            for value in payload.values():
                self.assert_payload_has_no_secret_material(value, *raw_values)
        elif isinstance(payload, list):
            for item in payload:
                self.assert_payload_has_no_secret_material(item, *raw_values)

    def test_cli_and_mcp_secret_surfaces_never_return_raw_values(self) -> None:
        repo_root = self.make_repo_root()
        secret_store = self.make_secret_store()
        secret = create_platform_secret(secret_store, label="OpenAI", raw_value="sk-top-secret", alias="default-openai")
        bind_workspace_secret(secret_store, workspace_id="default", logical_name="openai", secret_ref=build_secret_ref(alias=secret.alias))

        cli_context = CliInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="agent-1", effective_mode="sandbox")
        cli_result = run_core_cli_command(
            command_id="core.secrets.list",
            context=cli_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertEqual(cli_result["secrets"][0]["secret_id"], secret.secret_id)
        self.assert_payload_has_no_secret_material(cli_result, "sk-top-secret")

        mcp_context = McpInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        mcp_result = call_mcp_tool(
            tool_name="core.secrets.list",
            context=mcp_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertEqual(mcp_result["items"][0]["secret_id"], secret.secret_id)
        self.assertNotIn("raw_value", mcp_result["items"][0])

    def test_secret_metadata_update_surfaces_are_admin_only_and_preserve_refs(self) -> None:
        repo_root = self.make_repo_root()
        secret_store = self.make_secret_store()
        sandbox_context = CliInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="agent-1", effective_mode="sandbox")
        full_access_member_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-2",
            effective_mode="full-access",
            platform_role="member",
            workspace_role="member",
        )
        full_access_admin_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-3",
            effective_mode="full-access",
            platform_role="admin",
            workspace_role="admin",
        )
        operator_context = CliInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        mcp_context = McpInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        sandbox_mcp_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-sandbox",
            effective_mode="sandbox",
        )

        create_result = run_core_cli_command(
            command_id="core.secrets.create",
            context=operator_context,
            arguments={"label": "Recovery Key", "raw_value": "recovery-secret", "alias": "recovery-key"},
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        secret_id = create_result["secret"]["secret_id"]
        bind_workspace_secret(secret_store, workspace_id="default", logical_name="recovery", secret_ref=build_secret_ref(alias="recovery-key"))
        grant = grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="browser",
            logical_name="recovery",
            secret_ref=build_secret_ref(alias="recovery-key"),
            actions=["browser.autofill"],
            target_patterns=["https://example.com/*"],
        )
        list_result = run_core_cli_command(
            command_id="core.secrets.list",
            context=sandbox_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        bindings_result = run_core_cli_command(
            command_id="core.secrets.bindings.list",
            context=sandbox_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.secrets.rotate",
                context=sandbox_context,
                arguments={"secret_id": secret_id, "raw_value": "rotated-secret"},
                secret_store=secret_store,
                workspace_id="default",
                start_path=repo_root,
            )
        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.secrets.update",
                context=sandbox_context,
                arguments={"secret_id": secret_id, "alias": "sandbox-key"},
                secret_store=secret_store,
                workspace_id="default",
                start_path=repo_root,
            )
        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.secrets.update",
                context=full_access_member_context,
                arguments={"secret_id": secret_id, "alias": "member-key"},
                secret_store=secret_store,
                workspace_id="default",
                start_path=repo_root,
            )
        with self.assertRaises(McpInvocationNotAllowedError):
            call_mcp_tool(
                tool_name="core.secrets.update",
                context=sandbox_mcp_context,
                arguments={"secret_id": secret_id, "alias": "sandbox-key"},
                secret_store=secret_store,
                workspace_id="default",
                start_path=repo_root,
            )
        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.secrets.rotate",
                context=full_access_member_context,
                arguments={"secret_id": secret_id, "raw_value": "member-rotated-secret"},
                secret_store=secret_store,
                workspace_id="default",
                start_path=repo_root,
            )
        admin_rotate_result = run_core_cli_command(
            command_id="core.secrets.rotate",
            context=full_access_admin_context,
            arguments={"secret_id": secret_id, "raw_value": "admin-rotated-secret"},
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        update_result = run_core_cli_command(
            command_id="core.secrets.update",
            context=full_access_admin_context,
            arguments={
                "secret_id": secret_id,
                "alias": "renamed-recovery-key",
                "label": "Renamed Recovery Key",
                "description": "Rotated after recovery drill.",
                "kind": "api_key",
            },
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        binding_after_rename = run_core_cli_command(
            command_id="core.secrets.bindings.list",
            context=sandbox_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        grant_ref_after_rename = secret_store.get_secret_grant(grant.grant_id).secret_ref
        clear_alias_result = call_mcp_tool(
            tool_name="core.secrets.update",
            context=mcp_context,
            arguments={"secret_id": secret_id, "alias": None},
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        binding_after_clear = run_core_cli_command(
            command_id="core.secrets.bindings.list",
            context=sandbox_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertTrue(create_result["created"])
        self.assertTrue(admin_rotate_result["rotated"])
        self.assertTrue(update_result["updated"])
        self.assertTrue(clear_alias_result["updated"])
        self.assertEqual(update_result["secret"]["alias"], "renamed-recovery-key")
        self.assertEqual(update_result["secret"]["description"], "Rotated after recovery drill.")
        self.assertEqual(update_result["secret"]["kind"], "api_key")
        self.assertEqual(bindings_result["bindings"][0]["secret_ref"], "platform:secret-alias/recovery-key")
        self.assertEqual(binding_after_rename["bindings"][0]["secret_ref"], "platform:secret-alias/renamed-recovery-key")
        self.assertEqual(grant_ref_after_rename, "platform:secret-alias/renamed-recovery-key")
        self.assertEqual(secret_store.get_secret_grant(grant.grant_id).secret_ref, f"platform:secrets/{secret_id}")
        self.assertEqual(binding_after_clear["bindings"][0]["secret_ref"], f"platform:secrets/{secret_id}")
        self.assertEqual(secret_store.get_secret_value(secret_id=secret_id), "admin-rotated-secret")
        for payload in (
            create_result,
            admin_rotate_result,
            update_result,
            clear_alias_result,
            list_result,
            bindings_result,
            binding_after_rename,
            binding_after_clear,
        ):
            self.assert_payload_has_no_secret_material(payload, "recovery-secret", "rotated-secret", "admin-rotated-secret")

    def test_cli_and_mcp_expose_secret_create_and_recovery_health_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        secret_store = self.make_secret_store()
        recovery_store = self.make_recovery_store()
        runtime_store = self.make_runtime_store()
        provider_store = self.make_provider_store()
        register_builtin_providers(provider_store)
        provider_registry = ProviderRegistry()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-health",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )

        cli_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-cli",
            effective_mode="full-access",
            platform_role="admin",
            user_id="admin-user",
            runtime_session_id="sess-cli",
        )
        create_result = run_core_cli_command(
            command_id="core.secrets.create",
            context=cli_context,
            arguments={"label": "Recovery Key", "raw_value": "recovery-secret", "alias": "recovery-key"},
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertTrue(create_result["created"])
        self.assertNotIn("raw_value", create_result["secret"])

        mcp_context = McpInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        health_result = call_mcp_tool(
            tool_name="core.recovery.health",
            context=mcp_context,
            arguments={"target_kind": "runtime", "session_id": session.session_id},
            recovery_store=recovery_store,
            runtime_store=runtime_store,
            provider_registry=provider_registry,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertEqual(health_result["health"]["target_kind"], "runtime")

    def test_cli_and_mcp_secret_disable_and_revoke_cascade_grants(self) -> None:
        repo_root = self.make_repo_root()
        secret_store = self.make_secret_store()
        observability_store = self.make_observability_store()
        cli_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-cli",
            effective_mode="full-access",
            platform_role="admin",
            user_id="admin-user",
            runtime_session_id="sess-cli",
        )
        mcp_context = McpInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        cli_secret = create_platform_secret(secret_store, label="CLI Secret", raw_value="cli-secret", alias="cli-secret")
        cli_grants = [
            grant_app_secret_use(
                secret_store,
                workspace_id=workspace_id,
                app_id="browser",
                logical_name="login",
                secret_ref=build_secret_ref(alias=cli_secret.alias),
                actions=["browser.autofill"],
                target_patterns=["https://example.com/*"],
            )
            for workspace_id in ("default", "acme")
        ]
        mcp_secret = create_platform_secret(secret_store, label="MCP Secret", raw_value="mcp-secret", alias="mcp-secret")
        mcp_grants = [
            grant_app_secret_use(
                secret_store,
                workspace_id=workspace_id,
                app_id="browser",
                logical_name="backup",
                secret_ref=build_secret_ref(secret_id=mcp_secret.secret_id),
                actions=["browser.autofill"],
                target_patterns=["https://example.com/*"],
            )
            for workspace_id in ("default", "acme")
        ]

        cli_result = run_core_cli_command(
            command_id="core.secrets.disable",
            context=cli_context,
            arguments={"secret_id": cli_secret.secret_id},
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        mcp_result = call_mcp_tool(
            tool_name="core.secrets.revoke",
            context=mcp_context,
            arguments={"secret_id": mcp_secret.secret_id},
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cascade_audit = [
            item
            for item in observability_store.list_audit(source_domain="secrets")
            if item.action == "core.secrets.grant.revoke.cascade"
        ]
        cli_audit = [item for item in cascade_audit if item.payload["secret_id"] == cli_secret.secret_id]
        mcp_audit = [item for item in cascade_audit if item.payload["secret_id"] == mcp_secret.secret_id]

        self.assertEqual(cli_result["revoked_grant_count"], 2)
        self.assertEqual(mcp_result["revoked_grant_count"], 2)
        self.assertEqual({secret_store.get_secret_grant(grant.grant_id).status for grant in cli_grants + mcp_grants}, {"revoked"})
        self.assertEqual({item.workspace_id for item in cli_audit}, {"default", "acme"})
        self.assertEqual({item.workspace_id for item in mcp_audit}, {"default", "acme"})
        self.assertEqual({item.payload["grant_id"] for item in cli_audit}, {grant.grant_id for grant in cli_grants})
        self.assertEqual({item.payload["grant_id"] for item in mcp_audit}, {grant.grant_id for grant in mcp_grants})
        self.assertEqual({item.payload["app_id"] for item in cascade_audit}, {"browser"})
        self.assertEqual({item.payload["source_workspace_id"] for item in cascade_audit}, {"default"})
        self.assertEqual({item.runtime_session_id for item in cli_audit}, {"sess-cli"})
        self.assertEqual({item.payload["actor_agent_id"] for item in cli_audit}, {"agent-cli"})
        self.assertEqual({item.payload["actor_user_id"] for item in cli_audit}, {"admin-user"})

    def test_cli_and_mcp_secret_grant_admin_surfaces_validate_audit_and_redact(self) -> None:
        repo_root = self.make_repo_root()
        app_store = self.make_app_store()
        secret_store = self.make_secret_store()
        observability_store = self.make_observability_store()
        app_root = self.enable_secret_consumer_app(
            repo_root,
            app_store,
            secret_read=["api-token", "webhook-token"],
            backend=True,
            mcp_tools=["send"],
        )
        (app_root / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "mcp" / "tool_schemas.json").write_text(
            json.dumps({"tools": {"send": {"required_secrets": ["webhook-token"]}}}),
            encoding="utf-8",
        )
        secret = create_platform_secret(
            secret_store,
            label="Backend Token",
            raw_value="grant-secret",
            alias="backend-token",
        )
        cli_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-cli",
            effective_mode="full-access",
            platform_role="admin",
            user_id="admin-user",
            runtime_session_id="sess-cli",
        )
        sandbox_cli_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-sandbox",
            effective_mode="sandbox",
        )
        mcp_context = McpInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )
        sandbox_mcp_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-sandbox",
            effective_mode="sandbox",
        )

        command_by_id = {
            command.command_id: command
            for command in list_core_cli_commands(
                app_store=app_store,
                secret_store=secret_store,
                observability_store=observability_store,
                workspace_id="default",
                start_path=repo_root,
            )
        }
        tool_by_name = {
            tool.tool_name: tool
            for tool in list_mcp_tools(
                app_store=app_store,
                secret_store=secret_store,
                observability_store=observability_store,
                workspace_id="default",
                start_path=repo_root,
            )
        }
        self.assertIn("core.secret_grants.create", command_by_id)
        self.assertIn("core.secret_grants.create", tool_by_name)
        self.assertEqual(
            command_by_id["core.secret_grants.create"].argument_schema["required"],
            ["app_id", "logical_name", "actions"],
        )
        self.assertEqual(
            tool_by_name["core.secret_grants.create"].input_schema["required"],
            ["app_id", "logical_name", "actions"],
        )

        sandbox_list = run_core_cli_command(
            command_id="core.secret_grants.list",
            context=sandbox_cli_context,
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.secret_grants.create",
                context=sandbox_cli_context,
                arguments={
                    "app_id": "browser",
                    "logical_name": "api-token",
                    "secret_id": secret.secret_id,
                    "actions": ["app.backend"],
                    "target_patterns": [app_secret_target("backend")],
                },
                app_store=app_store,
                secret_store=secret_store,
                observability_store=observability_store,
                workspace_id="default",
                start_path=repo_root,
            )
        with self.assertRaises(McpInvocationNotAllowedError):
            call_mcp_tool(
                tool_name="core.secret_grants.create",
                context=sandbox_mcp_context,
                arguments={
                    "app_id": "browser",
                    "logical_name": "api-token",
                    "secret_id": secret.secret_id,
                    "actions": ["app.backend"],
                    "target_patterns": [app_secret_target("backend")],
                },
                app_store=app_store,
                secret_store=secret_store,
                observability_store=observability_store,
                workspace_id="default",
                start_path=repo_root,
            )

        cli_create = run_core_cli_command(
            command_id="core.secret_grants.create",
            context=cli_context,
            arguments={
                "app_id": "browser",
                "logical_name": "api-token",
                "secret_id": secret.secret_id,
                "actions": ["app.backend"],
                "target_patterns": [app_secret_target("backend")],
            },
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        with self.assertRaises(SecretPolicyError):
            run_core_cli_command(
                command_id="core.secret_grants.create",
                context=cli_context,
                arguments={
                    "app_id": "browser",
                    "logical_name": "api-token",
                    "secret_id": secret.secret_id,
                    "actions": ["app.backend"],
                    "target_patterns": [app_secret_target("backend")],
                },
                app_store=app_store,
                secret_store=secret_store,
                observability_store=observability_store,
                workspace_id="default",
                start_path=repo_root,
            )
        mcp_create = call_mcp_tool(
            tool_name="core.secret_grants.create",
            context=mcp_context,
            arguments={
                "app_id": "browser",
                "logical_name": "webhook-token",
                "secret_id": secret.secret_id,
                "actions": ["app.backend"],
                "target_patterns": [app_secret_target("mcp/send")],
            },
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        mcp_list = call_mcp_tool(
            tool_name="core.secret_grants.list",
            context=sandbox_mcp_context,
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        targets = run_core_cli_command(
            command_id="core.secret_grant_targets.list",
            context=sandbox_cli_context,
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        recommendations = call_mcp_tool(
            tool_name="core.secret_grant_targets.recommend",
            context=sandbox_mcp_context,
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        cli_revoke = run_core_cli_command(
            command_id="core.secret_grants.revoke",
            context=cli_context,
            arguments={"grant_id": cli_create["grant"]["grant_id"]},
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        mcp_revoke = call_mcp_tool(
            tool_name="core.secret_grants.revoke",
            context=mcp_context,
            arguments={"grant_id": mcp_create["grant"]["grant_id"]},
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        audit = run_core_cli_command(
            command_id="core.secret_audit.list",
            context=sandbox_cli_context,
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(sandbox_list["items"], [])
        self.assertTrue(cli_create["created"])
        self.assertTrue(mcp_create["created"])
        self.assertEqual(
            {item["grant_id"] for item in mcp_list["items"]},
            {cli_create["grant"]["grant_id"], mcp_create["grant"]["grant_id"]},
        )
        self.assertTrue(cli_revoke["revoked"])
        self.assertTrue(mcp_revoke["revoked"])
        self.assertTrue(any(item["app_id"] == "browser" for item in targets["items"]))
        self.assertTrue(
            any(item["recommended_grant"]["actions"] == ["app.backend"] for item in recommendations["items"])
        )
        self.assertEqual(
            [item.action for item in observability_store.list_audit(workspace_id="default")],
            [
                "core.secrets.grant.create",
                "core.secrets.grant.create",
                "core.secrets.grant.revoke",
                "core.secrets.grant.revoke",
            ],
        )
        self.assertEqual(len(audit["items"]), 4)
        self.assert_payload_has_no_secret_material(
            [cli_create, mcp_create, mcp_list, targets, recommendations, cli_revoke, mcp_revoke, audit],
            "grant-secret",
        )

    def test_cli_secret_grant_resource_scope_matches_app_consumers(self) -> None:
        repo_root = self.make_repo_root()
        app_store = self.make_app_store()
        secret_store = self.make_secret_store()
        observability_store = self.make_observability_store()
        app_root = self.enable_secret_consumer_app(
            repo_root,
            app_store,
            app_id="mail",
            secret_read=["refresh-token"],
            backend=False,
            cli_commands=["sync"],
        )
        (app_root / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "cli" / "command_schemas.json").write_text(
            json.dumps(
                {
                    "commands": {
                        "sync": {
                            "secret_selectors": [
                                {
                                    "required_secrets": ["refresh-token"],
                                    "resource_type": "mail_connection",
                                    "resource_lookup": {"kind": "connection_from_arguments"},
                                }
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        secret = create_platform_secret(secret_store, label="Refresh Token", raw_value="refresh-secret")
        cli_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-cli",
            effective_mode="full-access",
            platform_role="admin",
            user_id="admin-user",
        )

        with self.assertRaises(SecretPolicyError):
            run_core_cli_command(
                command_id="core.secret_grants.create",
                context=cli_context,
                arguments={
                    "app_id": "mail",
                    "logical_name": "refresh-token",
                    "secret_id": secret.secret_id,
                    "actions": ["app.backend"],
                    "target_patterns": [app_secret_target("cli/sync")],
                },
                app_store=app_store,
                secret_store=secret_store,
                observability_store=observability_store,
                workspace_id="default",
                start_path=repo_root,
            )
        with self.assertRaises(SecretPolicyError):
            run_core_cli_command(
                command_id="core.secret_grants.create",
                context=cli_context,
                arguments={
                    "app_id": "mail",
                    "logical_name": "refresh-token",
                    "secret_id": secret.secret_id,
                    "actions": ["app.backend"],
                    "target_patterns": [
                        app_secret_target("cli/sync", resource_type="mail_connection", resource_id="conn-2")
                    ],
                    "resource_type": "mail_connection",
                    "resource_id": "conn-1",
                },
                app_store=app_store,
                secret_store=secret_store,
                observability_store=observability_store,
                workspace_id="default",
                start_path=repo_root,
            )
        accepted = run_core_cli_command(
            command_id="core.secret_grants.create",
            context=cli_context,
            arguments={
                "app_id": "mail",
                "logical_name": "refresh-token",
                "secret_id": secret.secret_id,
                "actions": ["app.backend"],
                    "target_patterns": [
                        app_secret_target("cli/sync", resource_type="mail_connection", resource_id="conn-1")
                    ],
                "resource_type": "mail_connection",
                "resource_id": "conn-1",
            },
            app_store=app_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertTrue(accepted["created"])
        self.assertEqual(accepted["grant"]["resource_type"], "mail_connection")
        self.assert_payload_has_no_secret_material(accepted, "refresh-secret")

    def test_cli_and_mcp_recovery_hooks_plan_and_inspect_without_main_backend_dependency(self) -> None:
        repo_root = self.make_repo_root()
        runtime_store = self.make_runtime_store()
        recovery_store = self.make_recovery_store()
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        ensure_workspace_membership(
            workspace_store,
            membership_id="default:user-1",
            workspace_id="default",
            user_id="user-1",
            role="member",
        )
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
            owner_user_id="user-1",
            created_by_user_id="user-1",
            start_path=repo_root,
        )
        record_failed_start(
            recovery_store,
            category="missing_secret",
            detail="provider secret missing",
            workspace_id="default",
            session_id="sess-1",
        )

        cli_context = CliInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        restart_result = run_core_cli_command(
            command_id="core.recovery.restart",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id=session.session_id,
                effective_mode="sandbox",
                user_id="user-1",
                workspace_role="member",
            ),
            arguments={"session_id": session.session_id, "reason": "operator requested"},
            runtime_store=runtime_store,
            recovery_store=recovery_store,
            workspace_store=workspace_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertTrue(restart_result["executed"])

        mcp_context = McpInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        status_result = call_mcp_tool(
            tool_name="core.recovery.status",
            context=mcp_context,
            recovery_store=recovery_store,
            runtime_store=runtime_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertEqual(status_result["status"]["failure_count"], 1)
        self.assertEqual(status_result["status"]["latest_intent_action"], "restart_runtime")

        restart_tool_result = call_mcp_tool(
            tool_name="core.recovery.restart",
            context=McpInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id=session.session_id,
                effective_mode="sandbox",
                user_id="user-1",
                workspace_role="member",
            ),
            arguments={"session_id": session.session_id, "reason": "agent requested"},
            recovery_store=recovery_store,
            runtime_store=runtime_store,
            workspace_store=workspace_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertTrue(restart_tool_result["executed"])

    def test_cli_and_mcp_expose_explicit_backend_restart_surface(self) -> None:
        repo_root = self.make_repo_root()

        cli_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="full-access",
            workspace_role="admin",
        )
        with patch("core.cli.recovery_commands.restart_backend_service") as restart_backend:
            restart_backend.return_value.to_payload.return_value = {
                "service_name": "maverick-core.service",
                "health_url": "http://127.0.0.1:8014/health",
                "restarted": True,
                "method": "signal",
                "detail": "ok",
                "previous_pid": 10,
                "current_pid": 11,
                "active_state": "active",
                "sub_state": "running",
                "healthy": True,
            }
            cli_result = run_core_cli_command(
                command_id="core.recovery.restart_backend",
                context=cli_context,
                workspace_id="default",
                start_path=repo_root,
            )
        self.assertTrue(cli_result["restarted"])
        self.assertEqual(cli_result["command_id"], "core.recovery.restart_backend")

        mcp_context = McpInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="full-access",
            workspace_role="admin",
        )
        with patch("core.mcp.recovery_tools.restart_backend_service") as restart_backend:
            restart_backend.return_value.to_payload.return_value = {
                "service_name": "maverick-core.service",
                "health_url": "http://127.0.0.1:8014/health",
                "restarted": True,
                "method": "signal",
                "detail": "ok",
                "previous_pid": 10,
                "current_pid": 11,
                "active_state": "active",
                "sub_state": "running",
                "healthy": True,
            }
            mcp_result = call_mcp_tool(
                tool_name="core.recovery.restart_backend",
                context=mcp_context,
                workspace_id="default",
                start_path=repo_root,
            )
        self.assertTrue(mcp_result["restarted"])

    def test_backend_restart_surface_rejects_operator_and_non_default_workspace(self) -> None:
        repo_root = self.make_repo_root()

        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.recovery.restart_backend",
                context=CliInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access"),
                workspace_id="default",
                start_path=repo_root,
            )

        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.recovery.restart_backend",
                context=CliInvocationContext(
                    caller_kind="full_access_agent",
                    workspace_id="customer-a",
                    agent_id="agent-2",
                    effective_mode="full-access",
                ),
                workspace_id="customer-a",
                start_path=repo_root,
            )

        with self.assertRaises(McpInvocationNotAllowedError):
            call_mcp_tool(
                tool_name="core.recovery.restart_backend",
                context=McpInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access"),
                workspace_id="default",
                start_path=repo_root,
            )

        with self.assertRaises(McpInvocationNotAllowedError):
            call_mcp_tool(
                tool_name="core.recovery.restart_backend",
                context=McpInvocationContext(
                    caller_kind="full_access_agent",
                    workspace_id="customer-a",
                    agent_id="agent-2",
                    effective_mode="full-access",
                ),
                workspace_id="customer-a",
                start_path=repo_root,
            )
