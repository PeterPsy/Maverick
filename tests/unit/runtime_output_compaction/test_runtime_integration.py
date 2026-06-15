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
from core.runtime.execution_events import RuntimeExecutionEvent, parse_provider_json_event
from core.runtime.service import create_runtime_session
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


if __name__ == "__main__":
    unittest.main()
