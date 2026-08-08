"""Focused tests for the app-owned OpenDesign runtime translator."""

from __future__ import annotations

import json
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
import service  # noqa: E402


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

    def test_cleanup_data_directory_uses_strict_generation_control_without_bundle_verification(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            generation_root = root / "opendesign"
            (generation_root / "instances").mkdir(parents=True)
            (generation_root / "backups").mkdir()
            (generation_root / "migrations").mkdir()
            payload = self._payload(root)

            self.assertIsNone(runtime_bridge.cleanup_data_directory(payload))

            data_root = generation_root / "instances" / "gen_cleanup_fixture" / "data"
            data_root.mkdir(parents=True)

            (generation_root / "control.json").write_text(
                json.dumps(
                    {
                        "active": {
                            "bundle_artifact_sha256": "a" * 64,
                            "data_generation": "gen_cleanup_fixture",
                            "od_version": "0.16.1",
                        },
                        "migration_id": None,
                        "previous": None,
                        "schema_version": "1",
                        "updated_at": "2026-08-06T15:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(runtime_bridge.cleanup_data_directory(payload), data_root.resolve())

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

    def test_cancel_intent_dominates_late_failure_and_terminal_state_does_not_regress(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            with patch.object(runtime_bridge, "active_data_directory", return_value=active):
                canceled, _ = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_cancel_race",
                    conversation_id="od_conversation_cancel_race",
                    assistant_message_id="od_message_cancel_race",
                    client_request_id="client-cancel-race",
                    agent_id="maverick",
                )
                runtime_bridge.record_submission(
                    payload,
                    {
                        "od_run_id": canceled["od_run_id"],
                        "runtime_request_status": "submitted",
                        "runtime_session_id": "session-cancel-race",
                        "turn_id": "turn-cancel-race",
                        "stream_id": "stream-cancel-race",
                    },
                )
                runtime_bridge.mark_cancel_requested(payload, canceled["od_run_id"])
                terminal = runtime_bridge.record_terminal(
                    payload,
                    runtime_session_id="session-cancel-race",
                    turn_id="turn-cancel-race",
                    event_type="runtime.turn.failed",
                    files=[],
                )
                translated = runtime_bridge.translate_stream_events(
                    payload,
                    {
                        "od_run_id": canceled["od_run_id"],
                        "events": [
                            {
                                "stream_id": "stream-cancel-race",
                                "sequence": 1,
                                "event_type": "runtime.turn.failed",
                                "payload": {},
                            }
                        ],
                    },
                )

                succeeded, _ = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_terminal_race",
                    conversation_id="od_conversation_terminal_race",
                    assistant_message_id="od_message_terminal_race",
                    client_request_id="client-terminal-race",
                    agent_id="maverick",
                )
                runtime_bridge.record_submission(
                    payload,
                    {
                        "od_run_id": succeeded["od_run_id"],
                        "runtime_request_status": "submitted",
                        "runtime_session_id": "session-terminal-race",
                        "turn_id": "turn-terminal-race",
                        "stream_id": "stream-terminal-race",
                    },
                )
                runtime_bridge.record_terminal(
                    payload,
                    runtime_session_id="session-terminal-race",
                    turn_id="turn-terminal-race",
                    event_type="runtime.turn.completed",
                    files=[],
                )
                preserved = runtime_bridge.record_terminal(
                    payload,
                    runtime_session_id="session-terminal-race",
                    turn_id="turn-terminal-race",
                    event_type="runtime.turn.failed",
                    files=[],
                )

            self.assertIsNotNone(terminal)
            self.assertEqual(terminal["status"], "canceled")
            self.assertEqual(terminal["error"], "")
            self.assertEqual(translated["sse_events"][0]["data"]["status"], "canceled")
            self.assertIsNotNone(preserved)
            self.assertEqual(preserved["status"], "succeeded")
            self.assertEqual(preserved["result_package"]["run"]["status"], "succeeded")

    def test_platform_runtime_cleanup_deletes_only_matching_correlations(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = {
                **self._payload(root),
                "effective_mode": "full-access",
                "user_id": None,
            }
            with patch.object(runtime_bridge, "active_data_directory", return_value=active), patch.object(
                runtime_bridge,
                "cleanup_data_directory",
                return_value=active,
            ):
                records = {}
                for suffix in ("deleted", "retained"):
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
                    records[suffix] = record

                result = service.dispatch(
                    "runtime.cleanup_sessions",
                    payload,
                    {"runtime_session_ids": ["session-deleted", "session-missing", "session-deleted"]},
                )
                remaining = runtime_bridge.store_for_payload(payload).list()

            self.assertEqual(
                result,
                {
                    "cleaned_runtime_session_ids": ["session-deleted", "session-missing"],
                    "deleted_runtime_correlations": 1,
                },
            )
            self.assertEqual([record["od_run_id"] for record in remaining], [records["retained"]["od_run_id"]])

            with self.assertRaisesRegex(service.DesignStudioError, "trusted platform cleanup flow"):
                service.dispatch(
                    "runtime.cleanup_sessions",
                    self._payload(root),
                    {"runtime_session_ids": ["session-retained"]},
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
