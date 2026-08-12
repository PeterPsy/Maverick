from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import unittest

from core.runtime.errors import RuntimeTranscriptAccessError
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
            snapshot_newest_event_id=first["snapshot_newest_event_id"],
        )

        self.assertTrue(replay["projection_complete"])
        self.assertNotIn("late fallback", [message["content"] for message in replay["messages"]])
        with self.assertRaises(RuntimeTranscriptAccessError) as missing:
            read_runtime_transcript_message(
                store,
                context=self.context(),
                thread_id="session-1",
                message_id="client-turn-late",
                snapshot_newest_event_id=first["snapshot_newest_event_id"],
            )
        self.assertEqual(missing.exception.reason, "transcript_message_not_found")

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
