"""Split tests from tests/test_phase11_observability.py."""

from __future__ import annotations

from unittest.mock import patch

from core.cli.errors import CliInvocationNotAllowedError
from core.mcp.errors import McpInvocationNotAllowedError
from tests.phase11_observability_helpers import *


class TestPhase11SecretRecoverySurfaces(Phase11ObservabilityBase):
    """Focused test slice."""

    def test_cli_and_mcp_secret_surfaces_never_return_raw_values(self) -> None:
        repo_root = self.make_repo_root()
        secret_store = self.make_secret_store()
        secret = create_platform_secret(secret_store, label="OpenAI", raw_value="sk-top-secret", alias="default-openai")
        bind_workspace_secret(secret_store, workspace_id="default", logical_name="openai", secret_ref=build_secret_ref(alias=secret.alias))

        cli_context = CliInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        cli_result = run_core_cli_command(
            command_id="core.secrets.list",
            context=cli_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertEqual(cli_result["secrets"][0]["secret_id"], secret.secret_id)
        self.assertNotIn("raw_value", cli_result["secrets"][0])

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

        cli_context = CliInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
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

    def test_cli_and_mcp_recovery_hooks_plan_and_inspect_without_main_backend_dependency(self) -> None:
        repo_root = self.make_repo_root()
        runtime_store = self.make_runtime_store()
        recovery_store = self.make_recovery_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
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
            context=CliInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="agent-1", effective_mode="sandbox"),
            arguments={"session_id": session.session_id, "reason": "operator requested"},
            runtime_store=runtime_store,
            recovery_store=recovery_store,
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
            context=McpInvocationContext(caller_kind="sandbox_agent", workspace_id="default", agent_id="agent-1", effective_mode="sandbox"),
            arguments={"session_id": session.session_id, "reason": "agent requested"},
            recovery_store=recovery_store,
            runtime_store=runtime_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertTrue(restart_tool_result["executed"])

    def test_cli_and_mcp_expose_explicit_backend_restart_surface(self) -> None:
        repo_root = self.make_repo_root()

        cli_context = CliInvocationContext(caller_kind="full_access_agent", workspace_id="default", agent_id="agent-1", effective_mode="full-access")
        with patch("core.cli.recovery_commands.restart_backend_service") as restart_backend:
            restart_backend.return_value.to_payload.return_value = {
                "service_name": "maverick3-core.service",
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

        mcp_context = McpInvocationContext(caller_kind="full_access_agent", workspace_id="default", agent_id="agent-1", effective_mode="full-access")
        with patch("core.mcp.recovery_tools.restart_backend_service") as restart_backend:
            restart_backend.return_value.to_payload.return_value = {
                "service_name": "maverick3-core.service",
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
