"""Split tests from surface helper module."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from core.app_sdk.cli import run_cli_json
from core.apps.models import AppVisibilityDeclaration
from core.authorization.errors import AuthorizationError
from core.identity.service import create_user
from core.identity.store import IdentityCollections, IdentityDocumentStore
from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.store import build_inter_agent_document_store
from core.api.app_events import AppEventBus
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.runtime_session import RuntimeSessionGrantRecord
from core.runtime.thread_event_bus import RuntimeThreadEventBus
from core.secrets.errors import SecretPolicyError
from core.secrets.service import build_secret_ref, create_platform_secret, grant_app_secret_use
from core.secrets.store import SecretCollections, SecretDocumentStore
from core.workspaces.service import ensure_workspace_membership
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


def _group_chat_run_payload(*, run_id: str, root_session_id: str) -> dict:
    payload = _inter_agent_run_payload(run_id=run_id, root_session_id=root_session_id)
    payload["mode"] = "group_chat"
    payload["aggregator_participant_id"] = "researcher"
    payload["participants"][1]["execution_mode"] = "embedded_executor"
    payload["participants"][1].pop("agent_snapshot", None)
    payload["budget"] = {
        "max_participants": 3,
        "max_concurrent_participants": 1,
        "max_rounds": 1,
        "max_total_turns": 1,
        "max_turns_per_participant": 1,
    }
    return payload


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
        mcp_child = runtime_store.get_session("mcp-child")
        cli_child_root = Path(runtime_store.get_session("cli-child").runtime_root)
        mcp_child_root = Path(mcp_child.runtime_root)
        runtime_event_bus = RuntimeEventBus()
        runtime_thread_event_bus = RuntimeThreadEventBus()
        app_event_bus = AppEventBus()
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
            secret_store=object(),
            runtime_event_bus=runtime_event_bus,
            runtime_thread_event_bus=runtime_thread_event_bus,
            app_event_bus=app_event_bus,
            workspace_id="default",
            start_path=repo_root,
            arguments={"run_id": "cli-run", "reason": "test-close"},
        )
        mcp_close = call_mcp_tool(
            tool_name="inter_agent_close",
            context=mcp_context,
            app_store=app_store,
            workspace_store=workspace_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            secret_store=object(),
            runtime_event_bus=runtime_event_bus,
            runtime_thread_event_bus=runtime_thread_event_bus,
            app_event_bus=app_event_bus,
            workspace_id="default",
            start_path=repo_root,
            arguments={"run_id": "mcp-run", "reason": "test-close"},
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
        self.assertEqual(cli_child_skill_ids, [])
        self.assertIsNone(cli_spawn["runtime_session"]["system_prompt"])
        self.assertEqual(cli_spawn["runtime_session"]["grants"], [])
        self.assertEqual(mcp_create["run"]["run_id"], "mcp-run")
        self.assertEqual(mcp_spawn["runtime_session"]["session_kind"], "inter_agent_participant")
        self.assertEqual(mcp_spawn["runtime_session"]["thread_visibility"], "hidden")
        self.assertEqual(mcp_child.skill_ids, [])
        self.assertEqual(mcp_wait["run"]["run_id"], "mcp-run")
        self.assertEqual(cli_close["run"]["status"], "cancelled")
        self.assertEqual(mcp_close["run"]["status"], "cancelled")
        self.assertFalse(cli_child_root.exists())
        self.assertFalse(mcp_child_root.exists())
        with self.assertRaises(RuntimeSessionNotFoundError):
            runtime_store.get_session("cli-child")
        with self.assertRaises(RuntimeSessionNotFoundError):
            runtime_store.get_session("mcp-child")

    def test_inter_agent_cli_and_mcp_enforce_product_mode_gate(self) -> None:
        repo_root = self.make_repo_root()
        runtime_store = self.make_runtime_store()
        inter_agent_store = build_inter_agent_document_store(start_path=repo_root)
        create_runtime_session(
            runtime_store,
            session_id="root-cli-gated",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        create_runtime_session(
            runtime_store,
            session_id="root-mcp-gated",
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
        mcp_context = McpInvocationContext(**cli_context.__dict__)

        with self.assertRaisesRegex(InterAgentValidationError, "MAVERICK_FEATURE_GROUP_CHAT=1"):
            run_core_cli_command(
                command_id="inter-agent.runs.create",
                context=cli_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments=_group_chat_run_payload(run_id="cli-group-chat-disabled", root_session_id="root-cli-gated"),
            )
        with self.assertRaisesRegex(InterAgentValidationError, "MAVERICK_FEATURE_GROUP_CHAT=1"):
            call_mcp_tool(
                tool_name="inter_agent_run_create",
                context=mcp_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments=_group_chat_run_payload(run_id="mcp-group-chat-disabled", root_session_id="root-mcp-gated"),
            )
        for mode in ("handoff", "magentic_like"):
            payload = _inter_agent_run_payload(run_id=f"cli-{mode}", root_session_id="root-cli-gated")
            payload["mode"] = mode
            with self.assertRaisesRegex(InterAgentValidationError, "not product-facing"):
                run_core_cli_command(
                    command_id="inter-agent.runs.create",
                    context=cli_context,
                    runtime_store=runtime_store,
                    inter_agent_store=inter_agent_store,
                    workspace_id="default",
                    start_path=repo_root,
                    arguments=payload,
                )

        with patch.dict("os.environ", {"MAVERICK_FEATURE_GROUP_CHAT": "1"}):
            run_core_cli_command(
                command_id="inter-agent.runs.create",
                context=cli_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments=_group_chat_run_payload(run_id="cli-group-chat-enabled", root_session_id="root-cli-gated"),
            )
            call_mcp_tool(
                tool_name="inter_agent_run_create",
                context=mcp_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments=_group_chat_run_payload(run_id="mcp-group-chat-enabled", root_session_id="root-mcp-gated"),
            )

        with self.assertRaisesRegex(InterAgentValidationError, "MAVERICK_FEATURE_GROUP_CHAT=1"):
            run_core_cli_command(
                command_id="inter-agent.runs.execute",
                context=cli_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={"run_id": "cli-group-chat-enabled", "input_text": "Run gated mode."},
            )
        with self.assertRaisesRegex(InterAgentValidationError, "MAVERICK_FEATURE_GROUP_CHAT=1"):
            call_mcp_tool(
                tool_name="inter_agent_execute",
                context=mcp_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={"run_id": "mcp-group-chat-enabled", "input_text": "Run gated mode."},
            )

    def test_inter_agent_cli_and_mcp_reject_unsafe_child_session_id_as_validation_error(self) -> None:
        repo_root = self.make_repo_root()
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
        run_core_cli_command(
            command_id="inter-agent.runs.create",
            context=cli_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="unsafe-cli-run", root_session_id="root-cli"),
        )
        call_mcp_tool(
            tool_name="inter_agent_run_create",
            context=mcp_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="unsafe-mcp-run", root_session_id="root-mcp"),
        )

        with self.assertRaisesRegex(InterAgentValidationError, "runtime_session_id_unsafe"):
            run_core_cli_command(
                command_id="inter-agent.participants.spawn",
                context=cli_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={"run_id": "unsafe-cli-run", "participant_id": "researcher", "child_session_id": "../escape"},
            )
        with self.assertRaisesRegex(InterAgentValidationError, "runtime_session_id_unsafe"):
            call_mcp_tool(
                tool_name="inter_agent_participant_spawn",
                context=mcp_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={"run_id": "unsafe-mcp-run", "participant_id": "researcher", "child_session_id": "/tmp/evil"},
            )

    def test_inter_agent_cli_and_mcp_gate_controlled_synthetic_execution(self) -> None:
        repo_root = self.make_repo_root()
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
        run_core_cli_command(
            command_id="inter-agent.runs.create",
            context=cli_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="controlled-cli-run", root_session_id="root-cli"),
        )
        call_mcp_tool(
            tool_name="inter_agent_run_create",
            context=mcp_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="controlled-mcp-run", root_session_id="root-mcp"),
        )

        with self.assertRaisesRegex(AuthorizationError, "inter_agent_controlled_participants_forbidden"):
            run_core_cli_command(
                command_id="inter-agent.runs.execute",
                context=cli_context,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={
                    "run_id": "controlled-cli-run",
                    "controlled_participants": {"researcher": {"output_text": "synthetic cli"}},
                },
            )
        cli_result = run_core_cli_command(
            command_id="inter-agent.runs.execute",
            context=cli_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={
                "run_id": "controlled-cli-run",
                "allow_synthetic_participants": True,
                "controlled_participants": {"researcher": {"output_text": "synthetic cli"}},
                "project_summaries": False,
            },
        )
        mcp_result = call_mcp_tool(
            tool_name="inter_agent_execute",
            context=mcp_context,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={
                "run_id": "controlled-mcp-run",
                "allow_synthetic_participants": True,
                "controlled_participants": {"researcher": {"output_text": "synthetic mcp"}},
                "project_summaries": False,
            },
        )

        self.assertTrue(cli_result["participant_results"][0]["synthetic"])
        self.assertTrue(mcp_result["participant_results"][0]["synthetic"])
        cli_events = inter_agent_store.list_event_page("controlled-cli-run", workspace_id="default", visibility_plane="debug")
        self.assertTrue(any(event.payload.get("synthetic") is True for event in cli_events.events))

    def test_inter_agent_cli_and_mcp_reject_sandbox_non_creator_run_operations(self) -> None:
        repo_root = self.make_repo_root()
        identity_store = IdentityDocumentStore(
            IdentityCollections(
                users=FakeCollection(),
                credentials=FakeCollection(),
                auth_sessions=FakeCollection(),
            )
        )
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        creator = create_user(identity_store, username="ia.creator", password="owner-pass", platform_role="member")
        non_creator = create_user(identity_store, username="ia.other", password="other-pass", platform_role="member")
        for user in (creator, non_creator):
            ensure_workspace_membership(
                workspace_store,
                membership_id=f"default:{user.user_id}",
                workspace_id="default",
                user_id=user.user_id,
                role="member",
            )
        runtime_store = self.make_runtime_store()
        inter_agent_store = build_inter_agent_document_store(start_path=repo_root)
        create_runtime_session(
            runtime_store,
            session_id="owner-root",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            owner_user_id=creator.user_id,
            created_by_user_id=creator.user_id,
            start_path=repo_root,
        )
        creator_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="owner-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=creator.user_id,
            workspace_role="member",
        )
        non_creator_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="other-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=non_creator.user_id,
            workspace_role="member",
        )
        run_core_cli_command(
            command_id="inter-agent.runs.create",
            context=creator_context,
            identity_store=identity_store,
            workspace_store=workspace_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="owner-run", root_session_id="owner-root"),
        )

        with self.assertRaisesRegex(AuthorizationError, "inter_agent_run_operation_forbidden"):
            run_core_cli_command(
                command_id="inter-agent.runs.wait",
                context=non_creator_context,
                identity_store=identity_store,
                workspace_store=workspace_store,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={"run_id": "owner-run", "timeout_seconds": 0},
            )
        with self.assertRaisesRegex(AuthorizationError, "inter_agent_run_operation_forbidden"):
            call_mcp_tool(
                tool_name="inter_agent_participant_spawn",
                context=McpInvocationContext(**non_creator_context.__dict__),
                identity_store=identity_store,
                workspace_store=workspace_store,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments={"run_id": "owner-run", "participant_id": "researcher", "child_session_id": "forbidden-child"},
            )

    def test_inter_agent_cli_and_mcp_authorize_root_session_owner_or_explicit_grant(self) -> None:
        repo_root = self.make_repo_root()
        identity_store = IdentityDocumentStore(
            IdentityCollections(
                users=FakeCollection(),
                credentials=FakeCollection(),
                auth_sessions=FakeCollection(),
            )
        )
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        owner = create_user(identity_store, username="ia.root.owner", password="owner-pass", platform_role="member")
        other = create_user(identity_store, username="ia.root.other", password="other-pass", platform_role="member")
        for user in (owner, other):
            ensure_workspace_membership(
                workspace_store,
                membership_id=f"default:{user.user_id}",
                workspace_id="default",
                user_id=user.user_id,
                role="member",
            )
        runtime_store = self.make_runtime_store()
        inter_agent_store = build_inter_agent_document_store(start_path=repo_root)
        create_runtime_session(
            runtime_store,
            session_id="owned-root",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            owner_user_id=owner.user_id,
            created_by_user_id=owner.user_id,
            grants=[
                RuntimeSessionGrantRecord(
                    operation="inter_agent_root",
                    grantee_kind="user",
                    grantee_id=other.user_id,
                    issued_by_user_id=owner.user_id,
                )
            ],
            start_path=repo_root,
        )
        create_runtime_session(
            runtime_store,
            session_id="ungranted-root",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            owner_user_id=owner.user_id,
            created_by_user_id=owner.user_id,
            start_path=repo_root,
        )
        other_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="other-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=other.user_id,
            workspace_role="member",
        )

        with self.assertRaisesRegex(AuthorizationError, "inter_agent_root_session_forbidden"):
            run_core_cli_command(
                command_id="inter-agent.runs.create",
                context=other_context,
                identity_store=identity_store,
                workspace_store=workspace_store,
                runtime_store=runtime_store,
                inter_agent_store=inter_agent_store,
                workspace_id="default",
                start_path=repo_root,
                arguments=_inter_agent_run_payload(run_id="forbidden-root-run", root_session_id="ungranted-root"),
            )

        cli_result = run_core_cli_command(
            command_id="inter-agent.runs.create",
            context=other_context,
            identity_store=identity_store,
            workspace_store=workspace_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="granted-root-run", root_session_id="owned-root"),
        )
        mcp_result = call_mcp_tool(
            tool_name="inter_agent_run_create",
            context=McpInvocationContext(**other_context.__dict__),
            identity_store=identity_store,
            workspace_store=workspace_store,
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            workspace_id="default",
            start_path=repo_root,
            arguments=_inter_agent_run_payload(run_id="granted-root-run-mcp", root_session_id="owned-root"),
        )

        self.assertEqual(cli_result["run"]["run_id"], "granted-root-run")
        self.assertEqual(mcp_result["run"]["run_id"], "granted-root-run-mcp")

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

        operator_only_commands = [command.command_id for command in commands if command.invocation_policy.operator_only]
        self.assertIn("core.identity.reset-admin-password", operator_only_commands)
        self.assertIn("core.providers.hosted.activate", operator_only_commands)
        self.assertEqual(provider_result["providers"][0]["provider_id"], "codex")
        self.assertEqual(provider_result["providers"][0]["provider_role"], "runtime_engine")

    def test_cli_and_mcp_can_simulate_provider_routing(self) -> None:
        workspace_store = self.make_workspace_store()
        provider_store = self.make_provider_store()
        observability_store = ObservabilityDocumentStore(
            ObservabilityCollections(
                events=FakeCollection(),
                audit=FakeCollection(),
                metrics=FakeCollection(),
            )
        )
        secret_store = SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            ),
            key_loader=lambda: b"0" * 32,
        )
        ensure_default_workspace_record(workspace_store)
        register_builtin_providers(provider_store)
        secret = create_platform_secret(
            secret_store,
            label="Groq CLI MCP",
            raw_value="super-secret-token",
            alias="groq-cli-mcp",
            kind="api_key",
        )
        secret_ref = build_secret_ref(alias=secret.alias or "groq-cli-mcp")
        repo_root = self.make_repo_root()
        context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )
        operator_context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )
        mcp_context = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )
        mcp_operator_context = McpInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )

        activation = run_core_cli_command(
            command_id="core.providers.hosted.activate",
            context=operator_context,
            provider_store=provider_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"provider_id": "groq", "secret_ref": secret_ref},
        )
        surface = build_workspace_mcp_surface(
            workspace_store=workspace_store,
            provider_store=provider_store,
            secret_store=secret_store,
            observability_store=observability_store,
            workspace_id="default",
            start_path=repo_root,
        )
        mcp_activation = surface.call_tool(
            "core.providers.hosted.activate",
            {"provider_id": "groq", "secret_ref": secret_ref},
            context=mcp_operator_context,
        )

        cli_result = run_core_cli_command(
            command_id="core.providers.route",
            context=context,
            provider_store=provider_store,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"profile": "fast_model", "request_id": "req-cli"},
        )
        mcp_result = surface.call_tool(
            "core.providers.route",
            {"profile": "fast_model", "request_id": "req-mcp"},
            context=mcp_context,
        )

        self.assertEqual(activation["provider"]["status"], "active")
        self.assertEqual(mcp_activation["provider"]["status"], "active")
        self.assertEqual(cli_result["decision"]["request_id"], "req-cli")
        self.assertEqual(mcp_result["decision"]["request_id"], "req-mcp")
        self.assertEqual(cli_result["decision"]["candidate_provider_ids"], ["groq"])
        self.assertEqual(cli_result["decision"]["selected_provider_id"], "groq")
        self.assertEqual(mcp_result["decision"]["selected_provider_id"], "groq")
        self.assertNotIn("provider_disabled:groq", cli_result["decision"]["reason_codes"])
        self.assertNotIn("super-secret-token", str(activation))
        self.assertNotIn("secret_ref", str(cli_result))
        self.assertNotIn("secret_ref", str(mcp_result))
        activation_command = next(
            command
            for command in list_core_cli_commands(
                provider_store=provider_store,
                secret_store=secret_store,
                observability_store=observability_store,
                workspace_id="default",
                context=operator_context,
                start_path=repo_root,
            )
            if command.command_id == "core.providers.hosted.activate"
        )
        self.assertNotIn("binding_id", activation_command.argument_schema["properties"])
        audit_actions = [item.action for item in observability_store.list_audit(workspace_id="default")]
        event_types = [item.event_type for item in observability_store.list_events(workspace_id="default")]
        self.assertGreaterEqual(audit_actions.count("provider.hosted.activate"), 2)
        self.assertGreaterEqual(event_types.count("provider.hosted.activated"), 2)
        self.assertNotIn("super-secret-token", str(observability_store.list_audit(workspace_id="default")))
        self.assertNotIn(secret_ref, str(observability_store.list_events(workspace_id="default")))

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

    def test_app_cli_and_mcp_receive_dependency_resolution_payload(self) -> None:
        store = self.make_app_store()
        identity_store = IdentityDocumentStore(
            IdentityCollections(
                users=FakeCollection(),
                credentials=FakeCollection(),
                auth_sessions=FakeCollection(),
            )
        )
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        admin = create_user(identity_store, username="deps.admin", password="admin-pass", platform_role="member")
        member = create_user(identity_store, username="deps.member", password="member-pass", platform_role="member")
        ensure_workspace_membership(
            workspace_store,
            membership_id=f"default:{admin.user_id}",
            workspace_id="default",
            user_id=admin.user_id,
            role="admin",
        )
        ensure_workspace_membership(
            workspace_store,
            membership_id=f"default:{member.user_id}",
            workspace_id="default",
            user_id=member.user_id,
            role="member",
        )
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        provider_root = repo_root / "apps" / "storage-provider"
        write_app_contract_file(
            provider_root,
            build_parsed_app_contract(
                app_id="storage-provider",
                name="Storage Provider",
                version="1.0.0",
                description="Storage provider app.",
                publisher="maverick",
                contract=build_app_contract(
                    visibility=AppVisibilityDeclaration(
                        platform_roles=None,
                        workspace_roles=["admin"],
                        capabilities=None,
                    ),
                    provides=[
                        build_provided_interface_declaration(
                            interface="file.catalog",
                            description="File catalog.",
                            surfaces=["backend", "cli", "mcp"],
                        )
                    ],
                ),
            ),
        )
        consumer_root = repo_root / "apps" / "checklists"
        self.write_app_contract(
            consumer_root,
            requires=[
                build_required_interface_declaration(
                    alias="files",
                    interface="file.catalog",
                    description="File catalog provider.",
                )
            ],
        )
        provider_source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(provider_root),
            now=now,
        )
        install_store_app(store, source_id=provider_source.source_id, workspace_id="default", start_path=repo_root, now=now)
        consumer_source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(consumer_root),
            now=now,
        )
        install_store_app(store, source_id=consumer_source.source_id, workspace_id="default", start_path=repo_root, now=now)
        state = SimpleNamespace(
            repository_root=repo_root,
            app_store=store,
            identity_store=identity_store,
            workspace_store=workspace_store,
            runtime_store=None,
            provider_store=None,
            secret_store=None,
            recovery_store=None,
            observability_store=None,
            app_event_bus=None,
        )
        admin_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="deps-admin-runtime",
            effective_mode="full-access",
            platform_role="member",
            user_id=admin.user_id,
            workspace_role="admin",
        )
        member_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="deps-member-runtime",
            effective_mode="full-access",
            platform_role="member",
            user_id=member.user_id,
            workspace_role="member",
        )
        sandbox_admin_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="deps-admin-sandbox",
            effective_mode="sandbox",
            platform_role="member",
            user_id=admin.user_id,
            workspace_role="admin",
        )
        dependency_set_command = next(
            command
            for command in list_core_cli_commands(
                app_store=store,
                identity_store=identity_store,
                workspace_store=workspace_store,
                workspace_id="default",
                start_path=repo_root,
            )
            if command.command_id == "app.checklists.dependencies.set"
        )
        self.assertFalse(dependency_set_command.invocation_policy.sandbox_agent_allowed)
        with self.assertRaisesRegex(AuthorizationError, "app_dependency_management_forbidden"):
            run_cli_json(
                [
                    "core",
                    "cli",
                    "run",
                    "app.checklists.dependencies.set",
                    "--arguments-json",
                    '{"alias":"files","provider_app_ids":["storage-provider"]}',
                    "--json",
                ],
                state=state,
                repository_root=repo_root,
                trusted_context=member_context,
            )
        with self.assertRaises(CliInvocationNotAllowedError):
            run_cli_json(
                [
                    "core",
                    "cli",
                    "run",
                    "app.checklists.dependencies.set",
                    "--arguments-json",
                    '{"alias":"files","provider_app_ids":["storage-provider"]}',
                    "--json",
                ],
                state=state,
                repository_root=repo_root,
                trusted_context=sandbox_admin_context,
            )
        dependency_set = run_cli_json(
            [
                "core",
                "cli",
                "run",
                "app.checklists.dependencies.set",
                "--arguments-json",
                '{"alias":"files","provider_app_ids":["storage-provider"]}',
                "--json",
            ],
            state=state,
            repository_root=repo_root,
            trusted_context=admin_context,
        )
        dependency_status = run_cli_json(
            ["core", "cli", "run", "app.checklists.dependencies", "--json"],
            state=state,
            repository_root=repo_root,
            trusted_context=admin_context,
        )
        cli_context = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="full-access",
            platform_role="member",
            user_id=admin.user_id,
            workspace_role="admin",
        )
        mcp_context = McpInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="full-access",
            platform_role="member",
            user_id=admin.user_id,
            workspace_role="admin",
        )

        cli_result = run_core_cli_command(
            command_id="app.checklists.checklists",
            context=cli_context,
            app_store=store,
            identity_store=identity_store,
            workspace_store=workspace_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={},
        )
        mcp_result = call_mcp_tool(
            tool_name="app.checklists.checklists.list",
            context=mcp_context,
            app_store=store,
            identity_store=identity_store,
            workspace_store=workspace_store,
            workspace_id="default",
            start_path=repo_root,
            arguments={},
        )

        self.assertEqual(dependency_set["status"], "resolved")
        self.assertEqual(dependency_status["status"], "resolved")
        self.assertEqual(cli_result["app_dependencies"]["status"], "resolved")
        self.assertEqual(mcp_result["app_dependencies"]["status"], "resolved")
        self.assertEqual(
            cli_result["app_dependencies"]["dependencies"][0]["selected_provider_app_ids"],
            ["storage-provider"],
        )
        self.assertEqual(
            mcp_result["app_dependencies"]["dependencies"][0]["selected_provider_app_ids"],
            ["storage-provider"],
        )

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
            runtime_mode="plain_hosted_chat",
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
        surface = build_workspace_mcp_surface(
            workspace_store=workspace_store,
            provider_store=provider_store,
            runtime_store=runtime_store,
            workspace_id="default",
            start_path=repo_root,
        )
        mcp_result = surface.call_tool(
            "core.runtime.status",
            {"workspace_id": "default"},
            context=McpInvocationContext(
                caller_kind="operator",
                workspace_id="default",
                agent_id=None,
                effective_mode="full-access",
            ),
        )

        self.assertEqual(workspace_result["workspace"]["workspace_id"], "default")
        self.assertEqual(runtime_result["sessions"][0]["session_id"], "sess-1")
        self.assertEqual(runtime_result["sessions"][0]["runtime_mode"], "plain_hosted_chat")
        self.assertEqual(mcp_result["sessions"][0]["runtime_mode"], "plain_hosted_chat")
        self.assertEqual(provider_result["providers"][0]["provider_id"], "codex")
