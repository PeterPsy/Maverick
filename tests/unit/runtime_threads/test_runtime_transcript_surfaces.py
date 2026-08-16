from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.transcript_models import RuntimeTranscriptReadContext
from core.runtime.transcript_service import read_runtime_transcript
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


class RuntimeTranscriptSurfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )
        self.store.save_session(
            RuntimeSessionRecord(
                session_id="session-1",
                workspace_id="default",
                agent_id="chat",
                status="stopped",
                requested_mode=None,
                effective_mode="sandbox",
                workspace_root="/workspaces/default",
                workdir="/workspaces/default",
                runtime_root="/workspaces/default/runtime/sessions/session-1",
                started_at=NOW,
                updated_at=NOW,
                ended_at=NOW,
                last_progress_at=NOW,
                session_kind="chat_root",
                thread_visibility="user",
                source_app_id="design-studio",
                owner_user_id="alice",
            )
        )
        self.store.save_thread(
            RuntimeThreadRecord(
                thread_id="session-1",
                workspace_id="default",
                runtime_session_id="session-1",
                title="Design Studio launch",
                agent_label="Designer",
                agent_type_id="design-agent",
                agent_role_id="maker",
                source_app_id="design-studio",
                system_prompt=None,
                project_id="project-1",
                archived=False,
                availability="free",
                created_at=NOW,
                updated_at=NOW,
                last_user_message_at=NOW,
                last_completed_response_at=NOW,
            )
        )
        self.store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-1",
                session_id="session-1",
                workspace_id="default",
                status="completed",
                input_text="hello",
                created_at=NOW,
                updated_at=NOW + timedelta(seconds=2),
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=2),
                failure_reason=None,
                client_message_id="client-1",
            )
        )
        self.store.save_event(self.event("queued", "runtime.turn.queued", {"input_text": "hello"}))
        self.store.save_event(
            self.event("final", "runtime.output.final", {"complete_text": "answer"}, seconds=1)
        )

    def event(self, event_id: str, event_type: str, payload: dict, *, seconds: int = 0) -> RuntimeEventRecord:
        return RuntimeEventRecord(
            event_id=event_id,
            workspace_id="default",
            session_id="session-1",
            plane="turn",
            event_type=event_type,
            turn_id="turn-1",
            process_id=None,
            payload=payload,
            created_at=NOW + timedelta(seconds=seconds),
        )

    def test_cli_and_mcp_expose_all_three_authorized_transcript_surfaces(self) -> None:
        context_fields = {
            "caller_kind": "sandbox_agent",
            "workspace_id": "default",
            "agent_id": "caller-session",
            "effective_mode": "sandbox",
            "platform_role": "member",
            "user_id": "alice",
            "workspace_role": "member",
            "runtime_session_id": "caller-session",
        }
        cli_context = CliInvocationContext(**context_fields)
        mcp_context = McpInvocationContext(**context_fields)

        command_ids = {item.command_id for item in list_core_cli_commands(runtime_store=self.store)}
        tool_names = {item.tool_name for item in list_mcp_tools(runtime_store=self.store)}
        cli_list = run_core_cli_command(
            command_id="core.runtime.threads.list",
            context=cli_context,
            runtime_store=self.store,
            arguments={"source_app_id": "design-studio"},
        )
        cli_read = run_core_cli_command(
            command_id="core.runtime.transcript.read",
            context=cli_context,
            runtime_store=self.store,
            arguments={"thread_id": "session-1"},
        )
        mcp_message = call_mcp_tool(
            tool_name="core.runtime.transcript.message.read",
            context=mcp_context,
            runtime_store=self.store,
            arguments={"thread_id": "session-1", "message_id": "turn-1:agent", "max_chars": 3},
        )

        expected = {
            "core.runtime.threads.list",
            "core.runtime.transcript.read",
            "core.runtime.transcript.message.read",
        }
        self.assertTrue(expected.issubset(command_ids))
        self.assertTrue(expected.issubset(tool_names))
        self.assertEqual(cli_list["threads"][0]["thread_id"], "session-1")
        self.assertEqual(cli_read["messages"][-1]["content"], "answer")
        self.assertEqual(mcp_message["content"], "ans")

    def test_transcript_pages_reconstruct_messages_with_one_snapshot(self) -> None:
        context = RuntimeTranscriptReadContext(
            workspace_id="default",
            user_id="alice",
            platform_role="member",
            workspace_role="member",
            caller_runtime_session_id="caller-session",
        )

        newest = read_runtime_transcript(self.store, context=context, thread_id="session-1", limit=1)
        older = read_runtime_transcript(
            self.store,
            context=context,
            thread_id="session-1",
            limit=1,
            before_cursor=newest["page"]["next_before_cursor"],
            snapshot_cursor=newest["snapshot_cursor"],
        )

        self.assertTrue(newest["page"]["has_more_before"])
        self.assertFalse(older["page"]["has_more_before"])
        self.assertEqual(older["snapshot_cursor"], newest["snapshot_cursor"])
        self.assertEqual(
            [older["messages"][0]["content"], newest["messages"][0]["content"]],
            ["hello", "answer"],
        )


if __name__ == "__main__":
    unittest.main()
