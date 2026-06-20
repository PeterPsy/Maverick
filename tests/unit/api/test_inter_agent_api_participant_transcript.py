from __future__ import annotations

from datetime import UTC, datetime
import json
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.inter_agent.service import InterAgentService
from core.runtime.runtime_session import RuntimeSessionGrantRecord
from core.runtime.service import create_runtime_session, queue_runtime_turn, record_runtime_event, transition_runtime_turn
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport
from tests.unit.api.test_inter_agent_api import _run_payload_without_snapshot


class InterAgentParticipantTranscriptApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def _bootstrap_state(self, repo_root):
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            return bootstrap_platform_state(start_path=repo_root)

    def _create_root_session(self, state, repo_root) -> None:
        create_runtime_session(
            state.runtime_store,
            session_id="root-session",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            system_prompt="Parent prompt must not leak.",
            skill_ids=["parent-skill"],
            owner_user_id="parent-owner",
            grants=[
                RuntimeSessionGrantRecord(
                    operation="cleanup",
                    grantee_kind="user",
                    grantee_id="parent-owner",
                    issued_by_user_id="parent-owner",
                )
            ],
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )

    def test_projects_safe_product_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body={**_run_payload_without_snapshot(run_id="run-api-transcript"), "visibility_level": "detail"},
                cookie=cookie,
            )
            spawn_status, _spawn_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-transcript/participants",
                method="POST",
                body={"participant_id": "researcher", "child_session_id": "transcript-child"},
                cookie=cookie,
            )
            turn = queue_runtime_turn(
                state.runtime_store,
                turn_id="turn-transcript-1",
                session_id="transcript-child",
                input_text="Find launch facts.",
                now=now,
            )
            transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active", now=now)
            transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="completed", now=now)
            record_runtime_event(
                state.runtime_store,
                event_id="runtime-final-transcript-1",
                session_id="transcript-child",
                turn_id=turn.turn_id,
                plane="turn",
                event_type="runtime.output.final",
                payload={
                    "complete_text": "Research complete.",
                    "text": "Research complete.",
                    "raw_debug_payload": "must not leak",
                },
                now=now,
            )
            run = state.inter_agent_store.get_run("run-api-transcript", workspace_id="default")
            service = InterAgentService(state.inter_agent_store)
            service.record_event(
                run,
                event_type="inter_agent.task.completed",
                participant_id="researcher",
                runtime_session_id="transcript-child",
                runtime_turn_id=turn.turn_id,
                visibility_plane="detail",
                correlation_id="task-transcript",
                idempotency_key="task-transcript-completed",
                payload={
                    "summary": "Duplicate runtime result.",
                    "output_text": "Duplicate runtime result.",
                    "debug_payload": "must not leak",
                },
                now=now,
            )
            service.record_event(
                run,
                event_type="inter_agent.artifact.created",
                participant_id="researcher",
                visibility_plane="detail",
                correlation_id="artifact-transcript",
                idempotency_key="artifact-transcript-created",
                payload={
                    "artifact_refs": [
                        {
                            "label": "Research notes",
                            "workspace_relative_path": "storage/generated/research-notes.md",
                            "runtime_session_id": "must-not-leak",
                        }
                    ],
                    "partial_output": "Draft note summary.",
                    "debug_payload": "must not leak",
                },
                now=now,
            )
            transcript_status, transcript_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-transcript/participants/researcher/transcript",
                cookie=cookie,
            )

        serialized = json.dumps(transcript_payload)
        item_texts = [item["text"] for item in transcript_payload["items"]]
        self.assertEqual(create_status, 201)
        self.assertEqual(spawn_status, 201)
        self.assertEqual(transcript_status, 200)
        self.assertEqual(transcript_payload["participant"]["label"], "Researcher")
        self.assertEqual(transcript_payload["participant"]["status"], "running")
        self.assertNotIn("runtime_session_id", transcript_payload["participant"])
        self.assertIn("Find launch facts.", item_texts)
        self.assertIn("Research complete.", item_texts)
        self.assertTrue(any("Research notes" in text and "Draft note summary." in text for text in item_texts))
        self.assertNotIn("transcript-child", serialized)
        self.assertNotIn("turn-transcript-1", serialized)
        self.assertNotIn("runtime_session_id", serialized)
        self.assertNotIn("raw_debug_payload", serialized)
        self.assertNotIn("debug_payload", serialized)
        self.assertNotIn("Duplicate runtime result.", serialized)

    def test_applies_run_visibility_cap_to_inter_agent_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body={**_run_payload_without_snapshot(run_id="run-api-transcript-summary"), "visibility_level": "summary"},
                cookie=cookie,
            )
            run = state.inter_agent_store.get_run("run-api-transcript-summary", workspace_id="default")
            service = InterAgentService(state.inter_agent_store)
            service.record_event(
                run,
                event_type="inter_agent.task.completed",
                participant_id="researcher",
                visibility_plane="detail",
                correlation_id="detail-task",
                idempotency_key="run-api-transcript-summary:detail-task",
                payload={"output_text": "Detail output must not leak."},
            )
            transcript_status, transcript_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-transcript-summary/participants/researcher/transcript",
                cookie=cookie,
            )

        serialized = json.dumps(transcript_payload)
        self.assertEqual(create_status, 201)
        self.assertEqual(transcript_status, 200)
        self.assertEqual(transcript_payload["visibility_plane"], "summary")
        self.assertEqual(transcript_payload["item_count"], 0)
        self.assertNotIn("Detail output must not leak.", serialized)

    def test_applies_run_visibility_cap_to_runtime_turn_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body={**_run_payload_without_snapshot(run_id="run-api-transcript-runtime-summary"), "visibility_level": "summary"},
                cookie=cookie,
            )
            spawn_status, _spawn_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-transcript-runtime-summary/participants",
                method="POST",
                body={"participant_id": "researcher", "child_session_id": "runtime-summary-child"},
                cookie=cookie,
            )
            turn = queue_runtime_turn(
                state.runtime_store,
                turn_id="turn-runtime-summary",
                session_id="runtime-summary-child",
                input_text="DETAIL_RUNTIME_INPUT",
                now=now,
            )
            transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active", now=now)
            transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="completed", now=now)
            record_runtime_event(
                state.runtime_store,
                event_id="runtime-final-summary-cap",
                session_id="runtime-summary-child",
                turn_id=turn.turn_id,
                plane="turn",
                event_type="runtime.output.final",
                payload={"complete_text": "DETAIL_RUNTIME_OUTPUT", "text": "DETAIL_RUNTIME_OUTPUT"},
                now=now,
            )
            transcript_status, transcript_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-transcript-runtime-summary/participants/researcher/transcript",
                cookie=cookie,
            )

        serialized = json.dumps(transcript_payload)
        self.assertEqual(create_status, 201)
        self.assertEqual(spawn_status, 201)
        self.assertEqual(transcript_status, 200)
        self.assertEqual(transcript_payload["visibility_plane"], "summary")
        self.assertEqual(transcript_payload["item_count"], 0)
        self.assertNotIn("DETAIL_RUNTIME_INPUT", serialized)
        self.assertNotIn("DETAIL_RUNTIME_OUTPUT", serialized)

    def test_pages_back_until_participant_transcript_items_are_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body={**_run_payload_without_snapshot(run_id="run-api-transcript-paged"), "visibility_level": "detail"},
                cookie=cookie,
            )
            run = state.inter_agent_store.get_run("run-api-transcript-paged", workspace_id="default")
            service = InterAgentService(state.inter_agent_store)
            service.record_event(
                run,
                event_type="inter_agent.message.sent",
                participant_id="researcher",
                visibility_plane="detail",
                correlation_id="researcher-input",
                idempotency_key="run-api-transcript-paged:researcher-input",
                payload={"input_text": "Need early participant input."},
                now=now,
            )
            for index in range(300):
                service.record_event(
                    run,
                    event_type="inter_agent.summary.updated",
                    participant_id="orchestrator",
                    visibility_plane="detail",
                    correlation_id=f"orchestrator-tail-{index}",
                    idempotency_key=f"run-api-transcript-paged:orchestrator-tail-{index}",
                    payload={"summary": f"orchestrator tail {index}"},
                    now=now,
                )
            transcript_status, transcript_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-transcript-paged/participants/researcher/transcript?limit=80",
                cookie=cookie,
            )

        item_texts = [item["text"] for item in transcript_payload["items"]]
        self.assertEqual(create_status, 201)
        self.assertEqual(transcript_status, 200)
        self.assertEqual(transcript_payload["visibility_plane"], "detail")
        self.assertEqual(transcript_payload["item_count"], 1)
        self.assertFalse(transcript_payload["truncated"])
        self.assertIn("Need early participant input.", item_texts)

    def test_transcript_limit_keeps_newest_participant_items_after_paging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body={**_run_payload_without_snapshot(run_id="run-api-transcript-limit"), "visibility_level": "detail"},
                cookie=cookie,
            )
            run = state.inter_agent_store.get_run("run-api-transcript-limit", workspace_id="default")
            service = InterAgentService(state.inter_agent_store)
            for index in range(90):
                service.record_event(
                    run,
                    event_type="inter_agent.message.sent",
                    participant_id="researcher",
                    visibility_plane="detail",
                    correlation_id=f"researcher-input-{index}",
                    idempotency_key=f"run-api-transcript-limit:researcher-input-{index}",
                    payload={"input_text": f"participant input {index}"},
                    now=now,
                )
            for index in range(300):
                service.record_event(
                    run,
                    event_type="inter_agent.summary.updated",
                    participant_id="orchestrator",
                    visibility_plane="detail",
                    correlation_id=f"orchestrator-after-limit-{index}",
                    idempotency_key=f"run-api-transcript-limit:orchestrator-after-limit-{index}",
                    payload={"summary": f"orchestrator after {index}"},
                    now=now,
                )
            transcript_status, transcript_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-transcript-limit/participants/researcher/transcript?limit=80",
                cookie=cookie,
            )

        item_texts = [item["text"] for item in transcript_payload["items"]]
        self.assertEqual(create_status, 201)
        self.assertEqual(transcript_status, 200)
        self.assertEqual(transcript_payload["item_count"], 80)
        self.assertTrue(transcript_payload["truncated"])
        self.assertNotIn("participant input 0", item_texts)
        self.assertIn("participant input 89", item_texts)


if __name__ == "__main__":
    unittest.main()
