from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import unittest

from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.runtime.errors import RuntimeTranscriptAccessError
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionGrantRecord, RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.transcript_models import RuntimeTranscriptReadContext
from core.runtime.transcript_projection import project_runtime_transcript
from core.runtime.transcript_service import (
    list_runtime_transcript_threads,
    read_runtime_transcript,
    read_runtime_transcript_message,
)
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


class RuntimeTranscriptTest(unittest.TestCase):
    def memory_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def history_store(self) -> RuntimeDocumentStore:
        repo_root = make_temp_repo_root(self)
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=RuntimeSessionJsonCollection(start_path=repo_root, filename="session.json"),
                turns=RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json"),
                events=RuntimeEventJsonCollection(start_path=repo_root),
                processes=RuntimeSessionJsonCollection(start_path=repo_root, filename="processes.json"),
                states=RuntimeSessionJsonCollection(start_path=repo_root, filename="state.json"),
                threads=WorkspaceRuntimeJsonCollection(start_path=repo_root, filename="threads.json"),
            )
        )

    def session(
        self,
        session_id: str,
        *,
        workspace_id: str = "default",
        owner_user_id: str | None = "alice",
        status: str = "stopped",
        thread_visibility: str = "user",
        session_kind: str = "chat_root",
        grants: list | None = None,
    ) -> RuntimeSessionRecord:
        return RuntimeSessionRecord(
            session_id=session_id,
            workspace_id=workspace_id,
            agent_id="chat",
            status=status,  # type: ignore[arg-type]
            requested_mode=None,
            effective_mode="sandbox",
            workspace_root=f"/workspaces/{workspace_id}",
            workdir=f"/workspaces/{workspace_id}",
            runtime_root=f"/workspaces/{workspace_id}/runtime/sessions/{session_id}",
            started_at=NOW,
            updated_at=NOW,
            ended_at=NOW if status in {"stopped", "failed"} else None,
            last_progress_at=NOW,
            session_kind=session_kind,  # type: ignore[arg-type]
            thread_visibility=thread_visibility,  # type: ignore[arg-type]
            source_app_id="design-studio",
            owner_user_id=owner_user_id,
            grants=grants or [],
        )

    def thread(
        self,
        session_id: str,
        *,
        thread_id: str | None = None,
        workspace_id: str = "default",
        title: str = "Design Studio launch",
        created_at: datetime = NOW,
    ) -> RuntimeThreadRecord:
        return RuntimeThreadRecord(
            thread_id=thread_id or session_id,
            workspace_id=workspace_id,
            runtime_session_id=session_id,
            title=title,
            agent_label="Designer",
            agent_type_id="design-agent",
            agent_role_id="maker",
            source_app_id="design-studio",
            system_prompt="must never be projected",
            project_id="project-1",
            archived=False,
            availability="free",
            created_at=created_at,
            updated_at=created_at,
            last_user_message_at=created_at,
            last_completed_response_at=created_at,
        )

    def turn(
        self,
        turn_id: str,
        *,
        session_id: str = "session-1",
        input_text: str | None = "hello",
        status: str = "completed",
        client_message_id: str | None = "client-1",
    ) -> RuntimeTurnRecord:
        return RuntimeTurnRecord(
            turn_id=turn_id,
            session_id=session_id,
            workspace_id="default",
            status=status,  # type: ignore[arg-type]
            input_text=input_text,
            created_at=NOW,
            updated_at=NOW + timedelta(seconds=5),
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=5),
            failure_reason=None,
            client_message_id=client_message_id,
        )

    def event(
        self,
        event_id: str,
        event_type: str,
        payload: dict,
        *,
        session_id: str = "session-1",
        turn_id: str | None = "turn-1",
        seconds: int = 0,
    ) -> RuntimeEventRecord:
        return RuntimeEventRecord(
            event_id=event_id,
            workspace_id="default",
            session_id=session_id,
            plane="turn",
            event_type=event_type,
            turn_id=turn_id,
            process_id=None,
            payload=payload,
            created_at=NOW + timedelta(seconds=seconds),
        )

    def context(self, user_id: str = "alice", **overrides) -> RuntimeTranscriptReadContext:
        values = {
            "workspace_id": "default",
            "user_id": user_id,
            "platform_role": "member",
            "workspace_role": "member",
            "caller_runtime_session_id": "caller-session",
        }
        values.update(overrides)
        return RuntimeTranscriptReadContext(**values)

    def seed_conversation(self, store: RuntimeDocumentStore, *, session: RuntimeSessionRecord | None = None) -> None:
        target = session or self.session("session-1")
        store.save_session(target)
        store.save_thread(self.thread(target.session_id, workspace_id=target.workspace_id))
        turn = self.turn("turn-1", session_id=target.session_id)
        store.save_turn(turn)
        store.save_event(
            self.event(
                "event-queued",
                "runtime.turn.queued",
                {"input_text": "hello", "client_message_id": "client-1"},
                session_id=target.session_id,
            )
        )
        store.save_event(
            self.event(
                "event-final",
                "runtime.output.final",
                {"complete_text": "answer", "text": "answer"},
                session_id=target.session_id,
                seconds=2,
            )
        )

    def test_projection_keeps_steered_messages_and_does_not_duplicate_final_output(self) -> None:
        events = [
            self.event("queued", "runtime.turn.queued", {"input_text": "start", "client_message_id": "client-1"}),
            self.event("delta-1", "runtime.output.delta", {"text": "First. "}, seconds=1),
            self.event(
                "steered",
                "runtime.message.steered",
                {"input_text": "also test", "client_message_id": "client-2"},
                seconds=2,
            ),
            self.event("delta-2", "runtime.output.delta", {"text": "Second."}, seconds=3),
            self.event(
                "final",
                "runtime.output.final",
                {"text": "Second.", "complete_text": "First. Second."},
                seconds=4,
            ),
        ]

        projection = project_runtime_transcript(events, [self.turn("turn-1", input_text="start")])

        self.assertEqual(
            [(message.role, message.content) for message in projection.messages],
            [
                ("human", "start"),
                ("agent", "First. "),
                ("human", "also test"),
                ("agent", "Second."),
            ],
        )
        self.assertEqual(sum(message.content.count("Second.") for message in projection.messages), 1)

    def test_shared_frontend_projection_fixture_matches_python_projection(self) -> None:
        fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "runtime_transcript_projection.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                turn_document = dict(case["turn"])
                for key in ("created_at", "updated_at", "started_at", "completed_at"):
                    turn_document[key] = datetime.fromisoformat(turn_document[key])
                events = []
                for event_document in case["events"]:
                    document = dict(event_document)
                    document["created_at"] = datetime.fromisoformat(document["created_at"])
                    events.append(RuntimeEventRecord(**document))

                projection = project_runtime_transcript(events, [RuntimeTurnRecord(**turn_document)])

                self.assertEqual(
                    [
                        {"id": message.message_id, "role": message.role, "content": message.content}
                        for message in projection.messages
                    ],
                    case["expected_messages"],
                )

    def test_projection_uses_turn_input_fallback_and_filters_structured_runtime_fields(self) -> None:
        structured = self.event(
            "structured",
            "runtime.output.structured",
            {
                "structured_content": {
                    "kind": "checklist.design",
                    "payload": {
                        "title": "Launch",
                        "system_prompt": "hidden",
                        "raw_debug_payload": "hidden",
                        "provider_thread_id": "hidden",
                    },
                }
            },
        )

        projection = project_runtime_transcript([structured], [self.turn("turn-1", input_text="fallback input")])
        serialized = json.dumps([message.__dict__ for message in projection.messages], default=str)

        self.assertEqual(projection.messages[0].content, "fallback input")
        self.assertTrue(projection.messages[1].redactions_applied)
        self.assertNotIn("system_prompt", serialized)
        self.assertNotIn("raw_debug_payload", serialized)
        self.assertNotIn("provider_thread_id", serialized)
        self.assertNotIn("hidden", serialized)

    def test_catalog_filters_unauthorized_threads_before_query_and_pagination(self) -> None:
        store = self.memory_store()
        store.save_session(self.session("alice-thread", owner_user_id="alice"))
        store.save_session(self.session("bob-thread", owner_user_id="bob"))
        store.save_session(
            self.session(
                "hidden-thread",
                owner_user_id="alice",
                session_kind="inter_agent_participant",
                thread_visibility="hidden",
            )
        )
        store.save_thread(self.thread("alice-thread", title="Design Studio roadmap", created_at=NOW + timedelta(seconds=2)))
        store.save_thread(self.thread("bob-thread", title="Design Studio confidential", created_at=NOW + timedelta(seconds=1)))
        store.save_thread(self.thread("hidden-thread", title="Design Studio child"))

        payload = list_runtime_transcript_threads(
            store,
            context=self.context(),
            query="design studio",
            source_app_id="design-studio",
            limit=1,
        )

        self.assertEqual([item["thread_id"] for item in payload["threads"]], ["alice-thread"])
        self.assertFalse(payload["page"]["has_more"])

    def test_owner_admin_and_grant_can_read_stopped_session_but_other_member_cannot(self) -> None:
        store = self.memory_store()
        self.seed_conversation(store)

        owner = read_runtime_transcript(store, context=self.context("alice"), thread_id="session-1")
        admin = read_runtime_transcript(
            store,
            context=self.context("admin", workspace_role="admin"),
            thread_id="session-1",
        )
        with self.assertRaises(RuntimeTranscriptAccessError) as denied:
            read_runtime_transcript(store, context=self.context("bob"), thread_id="session-1")

        granted_session = replace(
            store.get_session("session-1"),
            grants=[
                RuntimeSessionGrantRecord(
                    operation="read_transcript",
                    grantee_kind="user",
                    grantee_id="bob",
                )
            ],
        )
        store.save_session(granted_session)
        granted = read_runtime_transcript(store, context=self.context("bob"), thread_id="session-1")

        self.assertEqual([item["content"] for item in owner["messages"]], ["hello", "answer"])
        self.assertEqual(admin["messages"], owner["messages"])
        self.assertEqual(granted["messages"], owner["messages"])
        self.assertEqual(denied.exception.reason, "transcript_read_forbidden")
        self.assertEqual(denied.exception.status_code, 403)

    def test_continuation_thread_projects_predecessor_and_successor_as_one_transcript(self) -> None:
        store = self.memory_store()
        predecessor = replace(
            self.session("session-1"),
            continuation_successor_session_id="session-2",
        )
        successor = replace(
            self.session("session-2", status="running"),
            predecessor_session_id="session-1",
            lineage_root_session_id="session-1",
        )
        store.save_session(predecessor)
        store.save_session(successor)
        store.save_thread(self.thread("session-2", thread_id="session-1"))
        store.save_turn(self.turn("turn-1", session_id="session-1"))
        store.save_event(
            self.event(
                "source-queued",
                "runtime.turn.queued",
                {"input_text": "hello", "client_message_id": "source-client"},
                session_id="session-1",
                turn_id="turn-1",
            )
        )
        store.save_event(
            self.event(
                "source-final",
                "runtime.output.final",
                {"complete_text": "first answer", "text": "first answer"},
                session_id="session-1",
                turn_id="turn-1",
                seconds=1,
            )
        )
        store.save_turn(
            self.turn(
                "turn-2",
                session_id="session-2",
                input_text="continue",
                client_message_id="successor-client",
            )
        )
        store.save_event(
            self.event(
                "successor-queued",
                "runtime.turn.queued",
                {"input_text": "continue", "client_message_id": "successor-client"},
                session_id="session-2",
                turn_id="turn-2",
                seconds=2,
            )
        )
        store.save_event(
            self.event(
                "successor-final",
                "runtime.output.final",
                {"complete_text": "continued answer", "text": "continued answer"},
                session_id="session-2",
                turn_id="turn-2",
                seconds=3,
            )
        )

        payload = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
        )

        self.assertEqual(
            [message["content"] for message in payload["messages"]],
            ["hello", "first answer", "continue", "continued answer"],
        )
        self.assertTrue(payload["projection_complete"])

    def test_cross_workspace_and_hidden_sessions_are_not_found(self) -> None:
        store = self.memory_store()
        store.save_session(self.session("other", workspace_id="other", owner_user_id="alice"))
        store.save_thread(self.thread("other", workspace_id="other"))
        hidden = self.session(
            "hidden",
            owner_user_id="alice",
            session_kind="inter_agent_participant",
            thread_visibility="hidden",
        )
        store.save_session(hidden)
        store.save_thread(self.thread("hidden"))

        for thread_id in ("other", "hidden"):
            with self.subTest(thread_id=thread_id), self.assertRaises(RuntimeTranscriptAccessError) as denied:
                read_runtime_transcript(store, context=self.context(), thread_id=thread_id)
            self.assertEqual(denied.exception.reason, "runtime_thread_not_found")
            self.assertEqual(denied.exception.status_code, 404)

    def test_history_reader_reconstructs_conversation_older_than_500_event_tail(self) -> None:
        store = self.history_store()
        session = self.session("session-1")
        store.save_session(session)
        store.save_thread(self.thread("session-1"))
        store.save_turn(self.turn("turn-1"))
        store.save_event(self.event("event-0000", "runtime.turn.queued", {"input_text": "old hello", "client_message_id": "old"}))
        for index in range(1, 502):
            store.save_event(
                self.event(
                    f"event-{index:04d}",
                    "runtime.step.updated",
                    {"label": f"step {index}"},
                    seconds=index,
                )
            )
        store.save_event(
            self.event(
                "event-0600",
                "runtime.output.final",
                {"complete_text": "complete answer", "text": "complete answer"},
                seconds=600,
            )
        )

        self.assertNotIn("event-0000", [event.event_id for event in store.list_events("session-1")])
        payload = read_runtime_transcript(store, context=self.context(), thread_id="session-1")
        store.save_event(
            self.event(
                "event-late-retroactive",
                "runtime.message.steered",
                {"input_text": "late retroactive"},
                seconds=1,
            )
        )
        replay = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            snapshot_cursor=payload["snapshot_cursor"],
        )

        self.assertEqual([item["content"] for item in payload["messages"]], ["old hello", "complete answer"])
        self.assertEqual([item["content"] for item in replay["messages"]], ["old hello", "complete answer"])
        self.assertTrue(payload["projection_complete"])
        self.assertTrue(payload["snapshot_cursor"].startswith("runtime.transcript.snapshot.v1."))

    def test_long_unicode_message_uses_explicit_windows_without_silent_loss(self) -> None:
        store = self.memory_store()
        session = self.session("session-1")
        store.save_session(session)
        store.save_thread(self.thread("session-1"))
        store.save_turn(self.turn("turn-1"))
        content = "😀éabcdef" * 4_000
        store.save_event(self.event("final", "runtime.output.final", {"complete_text": content, "text": content}))

        transcript = read_runtime_transcript(store, context=self.context(), thread_id="session-1")
        window = read_runtime_transcript_message(
            store,
            context=self.context(),
            thread_id="session-1",
            message_id="turn-1:agent",
            offset=1,
            max_chars=3,
            snapshot_cursor=transcript["snapshot_cursor"],
        )
        exhausted = read_runtime_transcript_message(
            store,
            context=self.context(),
            thread_id="session-1",
            message_id="turn-1:agent",
            offset=len(content) + 10,
            max_chars=3,
            snapshot_cursor=transcript["snapshot_cursor"],
        )

        agent_preview = next(item for item in transcript["messages"] if item["role"] == "agent")
        self.assertFalse(agent_preview["content_complete"])
        self.assertEqual(agent_preview["next_offset"], 2_000)
        self.assertEqual(window["content"], "éab")
        self.assertEqual(window["range_end"], 4)
        self.assertTrue(window["has_more"])
        self.assertFalse(window["complete"])
        self.assertEqual(exhausted["offset"], len(content))
        self.assertEqual(exhausted["range_end"], len(content))
        self.assertEqual(exhausted["content"], "")

    def test_redactions_are_explicit_and_audit_never_contains_conversation_text(self) -> None:
        store = self.memory_store()
        observability = ObservabilityDocumentStore(
            ObservabilityCollections(events=FakeCollection(), audit=FakeCollection(), metrics=FakeCollection())
        )
        session = self.session("session-1")
        store.save_session(session)
        store.save_thread(self.thread("session-1"))
        store.save_turn(self.turn("turn-1", input_text="Authorization: Bearer super-secret-value"))
        store.save_event(
            self.event(
                "queued",
                "runtime.turn.queued",
                {"input_text": "Authorization: Bearer super-secret-value", "client_message_id": "client-1"},
            )
        )

        payload = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            observability_store=observability,
            surface="cli",
        )
        with self.assertRaises(RuntimeTranscriptAccessError):
            read_runtime_transcript(
                store,
                context=self.context("bob"),
                thread_id="session-1",
                observability_store=observability,
                surface="mcp",
            )
        audit_json = json.dumps([record.__dict__ for record in observability.list_audit(workspace_id="default")], default=str)

        self.assertTrue(payload["redactions_applied"])
        self.assertNotIn("super-secret-value", json.dumps(payload, default=str))
        self.assertNotIn("super-secret-value", audit_json)
        self.assertNotIn("Authorization", audit_json)
        self.assertIn("target_thread_id", audit_json)
        self.assertIn("transcript_read_forbidden", audit_json)

    def test_cleanup_makes_transcript_unavailable(self) -> None:
        store = self.memory_store()
        self.seed_conversation(store)
        store.delete_session_records("session-1")
        store.delete_thread("session-1")

        with self.assertRaises(RuntimeTranscriptAccessError) as denied:
            read_runtime_transcript(store, context=self.context(), thread_id="session-1")

        self.assertEqual(denied.exception.reason, "runtime_thread_not_found")

if __name__ == "__main__":
    unittest.main()
