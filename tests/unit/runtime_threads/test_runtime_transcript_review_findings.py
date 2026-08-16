from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
import unittest

from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.transcript_models import RuntimeTranscriptReadContext
from core.runtime.transcript_payloads import message_payload
from core.runtime.transcript_projection import project_runtime_transcript
from core.runtime.transcript_service import read_runtime_transcript, read_runtime_transcript_message
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


class RuntimeTranscriptReviewFindingTest(unittest.TestCase):
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

    def turn(self, turn_id: str, input_text: str, *, seconds: int = 0) -> RuntimeTurnRecord:
        created_at = NOW + timedelta(seconds=seconds)
        return RuntimeTurnRecord(
            turn_id=turn_id,
            session_id="session-1",
            workspace_id="default",
            status="completed",
            input_text=input_text,
            created_at=created_at,
            updated_at=created_at + timedelta(seconds=1),
            started_at=created_at,
            completed_at=created_at + timedelta(seconds=1),
            failure_reason=None,
            client_message_id=f"client-{turn_id}",
        )

    def store(self) -> RuntimeDocumentStore:
        store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )
        store.save_session(
            RuntimeSessionRecord(
                session_id="session-1",
                workspace_id="default",
                agent_id="chat",
                status="running",
                requested_mode=None,
                effective_mode="sandbox",
                workspace_root="/workspaces/default",
                workdir="/workspaces/default",
                runtime_root="/workspaces/default/runtime/sessions/session-1",
                started_at=NOW,
                updated_at=NOW,
                ended_at=None,
                last_progress_at=NOW,
                owner_user_id="alice",
            )
        )
        store.save_thread(
            RuntimeThreadRecord(
                thread_id="session-1",
                workspace_id="default",
                runtime_session_id="session-1",
                title="Review findings",
                agent_label="chat",
                agent_type_id="",
                agent_role_id="",
                source_app_id="chat",
                system_prompt=None,
                project_id=None,
                archived=False,
                availability="active",
                created_at=NOW,
                updated_at=NOW,
                last_user_message_at=NOW,
                last_completed_response_at=NOW,
            )
        )
        return store

    def context(self) -> RuntimeTranscriptReadContext:
        return RuntimeTranscriptReadContext(
            workspace_id="default",
            user_id="alice",
            platform_role="member",
            workspace_role="member",
            caller_runtime_session_id="caller-session",
        )

    def test_structured_projection_blocks_forbidden_camel_case_keys(self) -> None:
        event = self.event(
            "structured",
            "runtime.output.structured",
            {
                "structured_content": {
                    "kind": "review.fixture",
                    "payload": {
                        "title": "visible",
                        "systemPrompt": "leak-system",
                        "developerPrompt": "leak-developer",
                        "providerThreadId": "leak-provider",
                        "workspaceRoot": "leak-workspace",
                    },
                }
            },
        )

        message = project_runtime_transcript([event], []).messages[0]
        serialized = json.dumps(message.structured_content)

        self.assertTrue(message.redactions_applied)
        self.assertIn("visible", serialized)
        self.assertNotIn("leak-", serialized)
        self.assertNotIn("Prompt", serialized)
        self.assertNotIn("ThreadId", serialized)
        self.assertNotIn("workspaceRoot", serialized)

    def test_event_watermark_excludes_later_turn_fallbacks_from_both_reads(self) -> None:
        store = self.store()
        store.save_turn(self.turn("turn-1", "first"))
        store.save_event(self.event("queued", "runtime.turn.queued", {"input_text": "first"}))
        store.save_event(
            self.event("final", "runtime.output.final", {"complete_text": "answer"}, seconds=2)
        )
        first = read_runtime_transcript(store, context=self.context(), thread_id="session-1")
        store.save_turn(self.turn("turn-late", "late fallback", seconds=10))

        replay = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            snapshot_cursor=first["snapshot_cursor"],
        )

        self.assertTrue(replay["projection_complete"])
        self.assertNotIn("late fallback", [message["content"] for message in replay["messages"]])
        with self.assertRaises(RuntimeTranscriptAccessError) as missing:
            read_runtime_transcript_message(
                store,
                context=self.context(),
                thread_id="session-1",
                message_id="client-turn-late",
                snapshot_cursor=first["snapshot_cursor"],
            )
        self.assertEqual(missing.exception.reason, "transcript_message_not_found")

    def test_snapshot_excludes_event_appended_later_with_earlier_timestamp(self) -> None:
        store = self.store()
        store.save_turn(self.turn("turn-1", "first"))
        store.save_event(self.event("queued", "runtime.turn.queued", {"input_text": "first"}))
        store.save_event(self.event("final", "runtime.output.final", {"complete_text": "answer"}, seconds=2))
        first = read_runtime_transcript(store, context=self.context(), thread_id="session-1")
        store.save_event(
            self.event(
                "late-steered",
                "runtime.message.steered",
                {"input_text": "written after snapshot"},
                seconds=1,
            )
        )

        replay = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            snapshot_cursor=first["snapshot_cursor"],
        )

        self.assertEqual([message["content"] for message in replay["messages"]], ["first", "answer"])
        self.assertTrue(replay["projection_complete"])

    def test_legacy_snapshot_survives_first_chunk_and_fresh_read_unifies_both(self) -> None:
        collection = RuntimeEventJsonCollection(start_path=make_temp_repo_root(self))
        query = {"workspace_id": "default", "session_id": "session-1"}
        legacy_events = [
            self.event("legacy-1", "runtime.turn.queued", {"input_text": "first"}),
            self.event("legacy-2", "runtime.output.final", {"complete_text": "answer"}, seconds=2),
        ]
        collection._write_documents(
            collection._legacy_history_path(workspace_id="default", session_id="session-1"),
            [asdict(event) for event in legacy_events],
        )
        legacy_page = collection.find_event_archive_page(
            query,
            before_position=None,
            snapshot_position=None,
            snapshot_event_id=None,
            limit=10,
        )

        chunk_event = self.event(
            "new-1",
            "runtime.message.steered",
            {"input_text": "written after migration"},
            seconds=3,
        )
        collection.append_history_upsert(
            {"event_id": chunk_event.event_id},
            {"$set": asdict(chunk_event)},
        )
        replay = collection.find_event_archive_page(
            query,
            before_position=None,
            snapshot_position=legacy_page["snapshot_position"],
            snapshot_event_id=legacy_page["snapshot_record_id"],
            limit=10,
        )
        fresh = collection.find_event_archive_page(
            query,
            before_position=None,
            snapshot_position=None,
            snapshot_event_id=None,
            limit=2,
        )
        older = collection.find_event_archive_page(
            query,
            before_position=fresh["oldest_position"],
            snapshot_position=fresh["snapshot_position"],
            snapshot_event_id=fresh["snapshot_record_id"],
            limit=2,
        )

        self.assertTrue(replay["snapshot_found"])
        self.assertEqual([event["event_id"] for event in replay["documents"]], ["legacy-1", "legacy-2"])
        self.assertTrue(fresh["has_more_before"])
        self.assertEqual(
            [event["event_id"] for event in older["documents"] + fresh["documents"]],
            ["legacy-1", "legacy-2", "new-1"],
        )

    def test_streamed_message_status_is_stable_within_snapshot(self) -> None:
        store = self.store()
        active_turn = replace(
            self.turn("turn-1", "first"),
            status="active",
            completed_at=None,
            updated_at=NOW,
        )
        store.save_turn(active_turn)
        store.save_event(self.event("queued", "runtime.turn.queued", {"input_text": "first"}))
        store.save_event(self.event("delta", "runtime.output.delta", {"text": "partial"}, seconds=1))
        first = read_runtime_transcript(store, context=self.context(), thread_id="session-1")

        store.save_turn(
            replace(
                active_turn,
                status="completed",
                completed_at=NOW + timedelta(seconds=2),
                updated_at=NOW + timedelta(seconds=2),
            )
        )
        replay = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            snapshot_cursor=first["snapshot_cursor"],
        )

        first_agent = next(message for message in first["messages"] if message["role"] == "agent")
        replay_agent = next(message for message in replay["messages"] if message["role"] == "agent")
        self.assertEqual(first_agent["status"], "pending")
        self.assertEqual(replay_agent["status"], "pending")
        self.assertEqual(replay["messages"], first["messages"])
        self.assertTrue(first["projection_complete"])
        self.assertTrue(replay["projection_complete"])

    def test_snapshot_cursor_rejects_malformed_input(self) -> None:
        store = self.store()

        with self.assertRaises(RuntimeTranscriptValidationError) as invalid:
            read_runtime_transcript(
                store,
                context=self.context(),
                thread_id="session-1",
                snapshot_cursor="runtime.transcript.snapshot.v1.not-base64!",
            )

        self.assertEqual(str(invalid.exception), "invalid_snapshot_cursor")

    def test_event_watermark_excludes_late_turn_with_equal_timestamp(self) -> None:
        store = self.store()
        store.save_turn(self.turn("turn-1", "first"))
        store.save_event(self.event("queued", "runtime.turn.queued", {"input_text": "first"}))
        store.save_event(self.event("final", "runtime.output.final", {"complete_text": "answer"}, seconds=2))
        first = read_runtime_transcript(store, context=self.context(), thread_id="session-1")
        store.save_turn(self.turn("turn-equal", "equal timestamp fallback", seconds=2))

        replay = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            snapshot_cursor=first["snapshot_cursor"],
        )

        self.assertNotIn("equal timestamp fallback", [message["content"] for message in replay["messages"]])
        with self.assertRaises(RuntimeTranscriptAccessError):
            read_runtime_transcript_message(
                store,
                context=self.context(),
                thread_id="session-1",
                message_id="client-turn-equal",
                snapshot_cursor=first["snapshot_cursor"],
            )

    def test_event_watermark_ignores_equal_timestamp_terminal_turn_mutation(self) -> None:
        store = self.store()
        original = replace(
            self.turn("turn-1", "first"),
            status="active",
            updated_at=NOW,
            completed_at=None,
        )
        store.save_turn(original)
        store.save_event(self.event("queued", "runtime.turn.queued", {"input_text": "first"}, seconds=2))
        first = read_runtime_transcript(store, context=self.context(), thread_id="session-1")
        store.save_turn(
            replace(
                original,
                status="failed",
                updated_at=NOW + timedelta(seconds=2),
                completed_at=NOW + timedelta(seconds=2),
                failure_reason="retroactive failure",
            )
        )

        replay = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            snapshot_cursor=first["snapshot_cursor"],
        )

        self.assertTrue(replay["projection_complete"])
        self.assertNotIn("retroactive failure", [message["content"] for message in replay["messages"]])

    def test_empty_event_snapshot_preserves_only_initial_turn_fallbacks(self) -> None:
        store = self.store()
        store.save_turn(self.turn("turn-1", "first fallback"))

        first = read_runtime_transcript(store, context=self.context(), thread_id="session-1")
        store.save_turn(self.turn("turn-2", "second fallback"))
        store.save_event(
            replace(
                self.event("late-queued", "runtime.turn.queued", {"input_text": "late event"}, seconds=1),
                turn_id="turn-2",
            )
        )
        replay = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            snapshot_cursor=first["snapshot_cursor"],
        )
        fallback_window = read_runtime_transcript_message(
            store,
            context=self.context(),
            thread_id="session-1",
            message_id="client-turn-1",
            snapshot_cursor=first["snapshot_cursor"],
        )

        self.assertEqual([message["content"] for message in first["messages"]], ["first fallback"])
        self.assertEqual([message["content"] for message in replay["messages"]], ["first fallback"])
        self.assertEqual(fallback_window["content"], "first fallback")
        self.assertFalse(first["projection_complete"])
        self.assertFalse(replay["projection_complete"])
        self.assertIn("turn_input_fallback_used:turn-1", first["projection_warnings"])

    def test_turn_input_fallback_fields_are_immutable_after_submission(self) -> None:
        store = self.store()
        original = replace(self.turn("turn-1", "original fallback"), invoked_skill_ids=["storage-ops"])
        store.save_turn(original)
        first = read_runtime_transcript(store, context=self.context(), thread_id="session-1")

        persisted = store.save_turn(
            replace(
                original,
                input_text="mutated fallback",
                client_message_id="mutated-client-id",
                invoked_skill_ids=["different-skill"],
                status="failed",
                failure_reason="later failure",
            )
        )
        replay = read_runtime_transcript(
            store,
            context=self.context(),
            thread_id="session-1",
            snapshot_cursor=first["snapshot_cursor"],
        )

        self.assertEqual(persisted.input_text, "original fallback")
        self.assertEqual(persisted.client_message_id, "client-turn-1")
        self.assertEqual(persisted.invoked_skill_ids, ["storage-ops"])
        self.assertEqual([message["content"] for message in replay["messages"]], ["original fallback"])
        self.assertNotIn("later failure", [message["content"] for message in replay["messages"]])

    def test_structured_projection_has_one_global_size_and_depth_budget(self) -> None:
        deep: dict = {"leaf": "visible"}
        for index in range(20):
            deep = {f"level_{index}": deep}
        event = self.event(
            "structured-large",
            "runtime.output.structured",
            {
                "structured_content": {
                    "kind": "review.large",
                    "payload": {
                        "deep": deep,
                        "wide": ["😀" * 4_000 for _index in range(100)],
                    },
                }
            },
        )

        message = project_runtime_transcript([event], []).messages[0]
        payload = message_payload(message, max_chars=2_000)
        serialized_bytes = len(json.dumps(payload["structured_content"], ensure_ascii=True).encode("utf-8"))

        self.assertLessEqual(serialized_bytes, 16_384)
        self.assertTrue(payload["structured_content_truncated"])
        self.assertFalse(payload["structured_content_complete"])
        self.assertEqual(
            payload["structured_content_serialized_bytes"],
            len(json.dumps(payload["structured_content"], ensure_ascii=True, separators=(",", ":")).encode("utf-8")),
        )
        self.assertTrue(payload["redactions_applied"])


if __name__ == "__main__":
    unittest.main()
