from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.api.runtime_websocket import runtime_event_frame
from core.providers.codex_app_server_runtime_notifications import _structured_content_from_completed_item
from core.runtime.execution_events import RuntimeExecutionEvent, parse_provider_json_event
from core.runtime.service import create_runtime_session, record_runtime_event
from core.runtime.turn_submission_service_events import _record_final_output
from core.runtime.turn_submission_service_output import _RuntimeTurnOutputRecorder


class RuntimeOutputCompactionIntegrationTest(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def make_state_and_session(self, *, session_id: str = "sess-final"):
        repo_root = self.make_repo_root()
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root, install_builtin_apps=False)
        session = create_runtime_session(
            state.runtime_store,
            session_id=session_id,
            workspace_id="default",
            agent_id="test-agent",
            start_path=repo_root,
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )
        return state, session

    def recorded_final_payload(self, *, deltas: list[str], output_text: str) -> dict:
        state, session = self.make_state_and_session()
        recorder = _RuntimeTurnOutputRecorder(state, session_id=session.session_id, turn_id="turn-final")
        for delta in deltas:
            recorder.record(RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": delta}))
        event = _record_final_output(
            state,
            session_id=session.session_id,
            turn_id="turn-final",
            provider_id="test-provider",
            output_text=recorder.final_text(output_text),
            complete_text=recorder.complete_text(output_text),
            exit_code=0,
        )
        return event.payload

    def test_provider_hook_lifecycle_noise_is_not_chat_facing_output(self) -> None:
        self.assertIsNone(parse_provider_json_event("hook started"))
        self.assertIsNone(parse_provider_json_event("hook completed"))
        self.assertIsNone(parse_provider_json_event('{"type": "hook.started"}'))
        self.assertIsNone(parse_provider_json_event('{"type": "hook.completed"}'))

    def test_provider_command_execution_is_compacted_before_persistence_and_live_frame(self) -> None:
        output = (
            "FAILED tests/test_runtime.py::test_tool_output - AssertionError\n"
            "Traceback (most recent call last):\n"
            "AssertionError: expected compact output\n"
            "short test summary info\n"
            "1 failed in 1.23s\n"
        ) + ("noise\n" * 20_000)
        provider_payload = {
            "type": "item.completed",
            "item": {
                "id": "cmd-1",
                "type": "commandExecution",
                "command": "pytest tests/test_runtime.py",
                "exitCode": 1,
                "aggregatedOutput": output,
            },
        }
        execution_event = parse_provider_json_event(json.dumps(provider_payload))
        self.assertIsNotNone(execution_event)

        repo_root = self.make_repo_root()
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root, install_builtin_apps=False)
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-compact",
            workspace_id="default",
            agent_id="test-agent",
            start_path=repo_root,
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )
        recorder = _RuntimeTurnOutputRecorder(state, session_id=session.session_id, turn_id="turn-compact")

        recorded = recorder.record(execution_event)

        payload = recorded.payload
        self.assertTrue(payload["output_compaction"]["applied"])
        self.assertIn("[tool output compacted]", payload["output"])
        self.assertNotIn("aggregatedOutput", payload["raw"]["item"])
        self.assertTrue(payload["raw"]["has_omitted_provider_payload"])
        frame = runtime_event_frame(recorded)
        self.assertTrue(frame["event"]["payload"]["output_compaction"]["applied"])
        self.assertNotIn("aggregatedOutput", frame["event"]["payload"]["raw"]["item"])
        self.assertIn("raw.item.aggregatedOutput", frame["event"]["payload"]["raw"]["omitted_provider_payload_fields"])

    def test_record_runtime_event_compacts_tool_payload_at_persistence_boundary(self) -> None:
        output = (
            "FAILED tests/test_boundary.py::test_direct_record - AssertionError\n"
            "Traceback (most recent call last):\n"
            "AssertionError: boundary compaction failed\n"
            "short test summary info\n"
        ) + ("persistence noise\n" * 12_000)
        repo_root = self.make_repo_root()
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root, install_builtin_apps=False)
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-boundary",
            workspace_id="default",
            agent_id="test-agent",
            start_path=repo_root,
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )

        recorded = record_runtime_event(
            state.runtime_store,
            event_id="event-boundary",
            session_id=session.session_id,
            turn_id="turn-boundary",
            process_id=None,
            plane="turn",
            event_type="runtime.tool_call.failed",
            payload={
                "name": "command",
                "status": "failed",
                "command": "python -m pytest tests/test_boundary.py",
                "exit_code": 1,
                "output": output,
                "raw": {"item": {"type": "commandExecution", "aggregatedOutput": output}},
            },
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )

        self.assertTrue(recorded.payload["output_compaction"]["applied"])
        self.assertIn("[tool output compacted]", recorded.payload["output"])
        self.assertNotIn("aggregatedOutput", recorded.payload["raw"]["item"])

    def test_record_runtime_event_does_not_trust_spoofed_compaction_metadata(self) -> None:
        output = (
            "API_TOKEN=spoofed-secret-value\n"
            "FAILED tests/test_boundary.py::test_spoofed_metadata - AssertionError\n"
            "Traceback (most recent call last):\n"
            "AssertionError: spoofed metadata bypassed compaction\n"
            "short test summary info\n"
        ) + ("spoofed metadata noise\n" * 12_000)
        repo_root = self.make_repo_root()
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root, install_builtin_apps=False)
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-spoofed-boundary",
            workspace_id="default",
            agent_id="test-agent",
            start_path=repo_root,
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )

        recorded = record_runtime_event(
            state.runtime_store,
            event_id="event-spoofed-boundary",
            session_id=session.session_id,
            turn_id="turn-spoofed-boundary",
            process_id=None,
            plane="turn",
            event_type="runtime.tool_call.failed",
            payload={
                "name": "command",
                "status": "failed",
                "command": "python -m pytest tests/test_boundary.py",
                "exit_code": 1,
                "output": output,
                "raw": {"item": {"type": "commandExecution", "aggregatedOutput": output}},
                "output_compaction": {
                    "version": 1,
                    "scope": "runtime_event_payload",
                    "applied": True,
                    "target_max_compacted_bytes": 24_000,
                },
            },
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )

        self.assertIn("[tool output compacted]", recorded.payload["output"])
        self.assertNotIn("spoofed-secret-value", str(recorded.payload))
        self.assertNotIn("aggregatedOutput", recorded.payload["raw"]["item"])

    def test_record_runtime_event_does_not_trust_spoofed_metadata_with_small_sensitive_raw(self) -> None:
        repo_root = self.make_repo_root()
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root, install_builtin_apps=False)
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-spoofed-sensitive-raw",
            workspace_id="default",
            agent_id="test-agent",
            start_path=repo_root,
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )

        recorded = record_runtime_event(
            state.runtime_store,
            event_id="event-spoofed-sensitive-raw",
            session_id=session.session_id,
            turn_id="turn-spoofed-sensitive-raw",
            process_id=None,
            plane="turn",
            event_type="runtime.tool_call.completed",
            payload={
                "name": "command",
                "status": "completed",
                "command": "printf ok",
                "exit_code": 0,
                "output": "ok",
                "raw": {
                    "item": {
                        "type": "commandExecution",
                        "metadata": {"api_key": "raw-short-secret"},
                    }
                },
                "output_compaction": {
                    "version": 1,
                    "scope": "runtime_event_payload",
                    "applied": False,
                    "target_max_compacted_bytes": 12_000,
                },
            },
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )

        self.assertEqual(recorded.payload["output"], "ok")
        self.assertEqual(recorded.payload["raw"]["item"]["metadata"]["api_key"], "<redacted>")
        self.assertNotIn("raw-short-secret", str(recorded.payload))

    def test_runtime_output_delta_is_not_compacted_and_still_feeds_final_text(self) -> None:
        repo_root = self.make_repo_root()
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root, install_builtin_apps=False)
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-delta",
            workspace_id="default",
            agent_id="test-agent",
            start_path=repo_root,
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )
        recorder = _RuntimeTurnOutputRecorder(state, session_id=session.session_id, turn_id="turn-delta")
        output = "hello " + ("Authorization: Bearer still-streamed " * 1000)

        recorded = recorder.record(RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": output}))

        self.assertEqual(recorded.payload["text"], output)
        self.assertNotIn("output_compaction", recorded.payload)
        self.assertEqual(recorder.final_text(output + "world"), "world")
        self.assertEqual(recorder.complete_text(output + "world"), output + "world")

    def test_final_event_carries_complete_text_when_full_answer_streamed_in_delta(self) -> None:
        payload = self.recorded_final_payload(
            deltas=["Answer streamed in deltas."],
            output_text="",
        )

        self.assertEqual(payload["text"], "")
        self.assertEqual(payload["complete_text"], "Answer streamed in deltas.")

    def test_final_event_carries_complete_text_when_final_is_suffix(self) -> None:
        payload = self.recorded_final_payload(
            deltas=["Hello "],
            output_text="Hello world",
        )

        self.assertEqual(payload["text"], "world")
        self.assertEqual(payload["complete_text"], "Hello world")

    def test_final_event_keeps_progress_delta_out_of_complete_final_answer(self) -> None:
        payload = self.recorded_final_payload(
            deltas=["Mi oriento sul codice e preparo il piano."],
            output_text="Final answer only.",
        )

        self.assertEqual(payload["text"], "Final answer only.")
        self.assertEqual(payload["complete_text"], "Final answer only.")

    def test_chat_render_structured_event_survives_long_tool_output_compaction(self) -> None:
        chat_render = {
            "kind": "dynamic.view.instance",
            "payload": {"id": "view_long", "title": "Long output view"},
        }
        cli_output = json.dumps(
            {
                "status_code": 200,
                "chat_render": chat_render,
                "items": [{"id": index, "name": f"item-{index}"} for index in range(3000)],
            }
        )
        item = {
            "id": "cmd-chat-render-long",
            "type": "commandExecution",
            "command": "maverick app dynamic-views mcp call render",
            "exitCode": 0,
            "aggregatedOutput": cli_output,
        }
        structured = _structured_content_from_completed_item(provider_type="item.completed", item=item)
        self.assertEqual(structured, chat_render)
        execution_event = parse_provider_json_event(json.dumps({"type": "item.completed", "item": item}))
        self.assertIsNotNone(execution_event)

        repo_root = self.make_repo_root()
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root, install_builtin_apps=False)
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-chat-render-compact",
            workspace_id="default",
            agent_id="test-agent",
            start_path=repo_root,
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )
        recorder = _RuntimeTurnOutputRecorder(state, session_id=session.session_id, turn_id="turn-chat-render")

        recorded_tool = recorder.record(execution_event)
        recorded_structured = recorder.record(
            RuntimeExecutionEvent(
                event_type="runtime.output.structured",
                payload={
                    "structured_content": structured,
                    "provider_event_type": "item.completed",
                    "tool_call_id": item["id"],
                },
            )
        )

        self.assertTrue(recorded_tool.payload["output_compaction"]["applied"])
        self.assertEqual(recorded_tool.payload["output_compaction"]["rule_id"], "data/json_large")
        self.assertNotIn("aggregatedOutput", recorded_tool.payload["raw"]["item"])
        self.assertNotIn("output_compaction", recorded_structured.payload)
        self.assertEqual(recorded_structured.payload["structured_content"]["kind"], "dynamic.view.instance")
        self.assertEqual(recorded_structured.payload["structured_content"]["payload"]["id"], "view_long")


if __name__ == "__main__":
    unittest.main()
