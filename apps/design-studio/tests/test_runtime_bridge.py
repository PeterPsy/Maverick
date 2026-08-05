"""Focused tests for the app-owned OpenDesign runtime translator."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import runtime_bridge  # noqa: E402


class DesignStudioRuntimeBridgeTests(unittest.TestCase):
    def _payload(self, root: Path) -> dict[str, str]:
        return {
            "workspace_id": "default",
            "app_id": "design-studio",
            "sidecar_id": "opendesign",
            "user_id": "user:admin",
            "data_root": str(root),
        }

    def test_correlation_is_idempotent_redaction_safe_and_replayable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            with patch.object(runtime_bridge, "active_data_directory", return_value=active):
                record, inserted = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_fixture",
                    conversation_id="od_conversation_fixture",
                    assistant_message_id="od_message_fixture",
                    client_request_id="client-request-one",
                    agent_id="maverick",
                )
                replay, replay_inserted = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_fixture",
                    conversation_id="od_conversation_fixture",
                    assistant_message_id="od_message_fixture",
                    client_request_id="client-request-one",
                    agent_id="maverick",
                )
                runtime_bridge.record_submission(
                    payload,
                    {
                        "od_run_id": record["od_run_id"],
                        "runtime_request_status": "submitted",
                        "runtime_session_id": "session-one",
                        "turn_id": "turn-one",
                        "stream_id": "stream-one",
                        "actor_id": "user:admin",
                    },
                )
                batch = {
                    "od_run_id": record["od_run_id"],
                    "events": [
                        {
                            "stream_id": "stream-one",
                            "sequence": 1,
                            "event_type": "runtime.turn.started",
                            "payload": {},
                        },
                        {
                            "stream_id": "stream-one",
                            "sequence": 2,
                            "event_type": "runtime.output.delta",
                            "payload": {"text": "Creating the design."},
                        },
                    ],
                }
                first = runtime_bridge.translate_stream_events(payload, batch)
                replayed = runtime_bridge.translate_stream_events(payload, batch)
                stored = runtime_bridge.store_for_payload(payload).get(record["od_run_id"])

            self.assertTrue(inserted)
            self.assertFalse(replay_inserted)
            self.assertEqual(replay["od_run_id"], record["od_run_id"])
            self.assertEqual(first, replayed)
            self.assertEqual(first["ack_sequence"], 2)
            self.assertEqual(first["sse_events"][1]["data"], {"type": "text_delta", "delta": "Creating the design."})
            self.assertEqual(stored["last_sequence"], 2)
            persisted = (active / runtime_bridge.BRIDGE_DIRECTORY / runtime_bridge.CORRELATIONS_FILE).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("Creating the design", persisted)
            self.assertNotIn("client-request-one", persisted)

    def test_terminal_packages_cover_success_failure_and_cancel(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            with patch.object(runtime_bridge, "active_data_directory", return_value=active):
                packages: dict[str, dict] = {}
                for suffix, event_type, expected in (
                    ("success", "runtime.turn.completed", "succeeded"),
                    ("failure", "runtime.turn.failed", "failed"),
                    ("cancel", "runtime.turn.cancelled", "canceled"),
                ):
                    record, _ = runtime_bridge.reserve_run(
                        payload,
                        project_id=f"od_project_{suffix}",
                        conversation_id=f"od_conversation_{suffix}",
                        assistant_message_id=f"od_message_{suffix}",
                        client_request_id=f"client-{suffix}",
                        agent_id="maverick",
                    )
                    runtime_bridge.record_submission(
                        payload,
                        {
                            "od_run_id": record["od_run_id"],
                            "runtime_request_status": "submitted",
                            "runtime_session_id": f"session-{suffix}",
                            "turn_id": f"turn-{suffix}",
                            "stream_id": f"stream-{suffix}",
                        },
                    )
                    terminal = runtime_bridge.record_terminal(
                        payload,
                        runtime_session_id=f"session-{suffix}",
                        turn_id=f"turn-{suffix}",
                        event_type=event_type,
                        files=[{"name": "index.html"}],
                    )
                    self.assertIsNotNone(terminal)
                    self.assertEqual(terminal["status"], expected)
                    packages[expected] = terminal["result_package"]

            self.assertEqual(set(packages), {"succeeded", "failed", "canceled"})
            for status, package in packages.items():
                self.assertEqual(package["run"]["status"], status)
                self.assertEqual(package["artifacts"][0]["file"], "index.html")
                self.assertEqual(package["maverick"]["workspace_id"], "default")
                self.assertEqual(package["maverick"]["od_project_id"], f"od_project_{'success' if status == 'succeeded' else 'failure' if status == 'failed' else 'cancel'}")
                self.assertEqual(package["maverick"]["od_run_id"], package["run"]["runId"])
                self.assertEqual(
                    set(package["maverick"]),
                    {
                        "workspace_id",
                        "local_app_id",
                        "sidecar_id",
                        "od_project_id",
                        "od_run_id",
                        "request_id",
                        "correlation_id",
                        "runtime_session_id",
                        "turn_id",
                    },
                )

    def test_translator_rejects_foreign_stream_and_unknown_event(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            with patch.object(runtime_bridge, "active_data_directory", return_value=active):
                record, _ = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_fixture",
                    conversation_id="od_conversation_fixture",
                    assistant_message_id="od_message_fixture",
                    client_request_id="client-request-two",
                    agent_id="maverick",
                )
                runtime_bridge.record_submission(
                    payload,
                    {
                        "od_run_id": record["od_run_id"],
                        "runtime_request_status": "submitted",
                        "runtime_session_id": "session-one",
                        "turn_id": "turn-one",
                        "stream_id": "stream-one",
                    },
                )
                with self.assertRaisesRegex(runtime_bridge.RuntimeBridgeError, "ownership mismatch"):
                    runtime_bridge.translate_stream_events(
                        payload,
                        {
                            "od_run_id": record["od_run_id"],
                            "events": [
                                {
                                    "stream_id": "foreign-stream",
                                    "sequence": 1,
                                    "event_type": "runtime.turn.started",
                                    "payload": {},
                                }
                            ],
                        },
                    )
                with self.assertRaisesRegex(runtime_bridge.RuntimeBridgeError, "identity is invalid"):
                    runtime_bridge.translate_stream_events(
                        payload,
                        {
                            "od_run_id": record["od_run_id"],
                            "events": [
                                {
                                    "stream_id": "stream-one",
                                    "sequence": 1,
                                    "event_type": "runtime.provider.raw",
                                    "payload": {"secret": True},
                                }
                            ],
                        },
                    )


if __name__ == "__main__":
    unittest.main()
