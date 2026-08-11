"""Focused tests for the app-owned OpenDesign runtime translator."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
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

    def test_launch_target_prefers_deep_link_then_latest_creation_and_has_real_empty_state(self) -> None:
        projects = [
            {
                "id": "od_created_first",
                "name": "Updated most recently",
                "createdAt": "2026-08-01T10:00:00Z",
                "updatedAt": "2026-08-11T10:00:00Z",
            },
            {
                "id": "od_created_last",
                "name": "Created most recently",
                "createdAt": "2026-08-10T10:00:00Z",
                "updatedAt": "2026-08-10T10:00:00Z",
            },
        ]
        payload = self._payload(Path("/tmp/design-studio-launch-test"))
        with patch.object(service, "list_opendesign_projects", return_value={"projects": projects}):
            automatic = service.resolve_launch_target(payload, {})
            deep_link = service.resolve_launch_target(payload, {"od_project_id": "od_created_first"})
        with patch.object(service, "list_opendesign_projects", return_value={"projects": []}):
            empty = service.resolve_launch_target(payload, {})

        self.assertEqual(automatic["od_project_id"], "od_created_last")
        self.assertEqual(deep_link["od_project_id"], "od_created_first")
        self.assertEqual(empty, {"target": "empty", "od_project_id": "", "project": None})

    def test_chat_capabilities_expose_only_actionable_modes_and_mounted_owner(self) -> None:
        payload = self._payload(Path("/tmp/design-studio-capability-test"))
        payload["app_id"] = "mounted-design-studio"
        capabilities = service.chat_capabilities(payload)
        self.assertEqual(capabilities["source_app_id"], "mounted-design-studio")
        self.assertEqual(capabilities["modes"], ["chat", "plan", "design"])
        self.assertNotIn("supported", capabilities)
        self.assertNotIn("unavailable", capabilities)

    def test_active_generation_verification_is_reused_within_one_backend_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "opendesign").mkdir()
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            with patch.object(runtime_bridge, "read_bundle_manifest", return_value={}), patch.object(
                runtime_bridge,
                "resolve_runtime_binding",
                return_value=SimpleNamespace(data_dir=active),
            ) as resolve:
                first = runtime_bridge.active_data_directory(payload)
                second = runtime_bridge.active_data_directory(payload)

            self.assertEqual(first, active)
            self.assertEqual(second, active)
            resolve.assert_called_once()

    def test_core_runtime_surfaces_reuse_strict_generation_control_without_rehashing_bundle(self) -> None:
        with TemporaryDirectory() as temp_dir:
            active = Path(temp_dir) / "active"
            active.mkdir()
            payload = self._payload(Path(temp_dir))
            payload["surface"] = "runtime_stream_translation"
            with patch.object(runtime_bridge, "cleanup_data_directory", return_value=active) as resolve_control, patch.object(
                runtime_bridge,
                "active_data_directory",
                side_effect=AssertionError("trusted runtime callbacks must not rehash the bundle"),
            ):
                runtime_bridge.store_for_payload(payload)
                runtime_bridge.binding_store_for_payload(payload)

            self.assertEqual(resolve_control.call_count, 2)

    def test_core_sidecar_run_metadata_can_be_marked_trusted_only_after_routing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            active = Path(temp_dir) / "active"
            active.mkdir()
            payload = self._payload(Path(temp_dir))
            payload["surface"] = "sidecar_core_handler"
            trusted = runtime_bridge.trusted_sidecar_runtime_metadata_payload(payload)
            with patch.object(runtime_bridge, "cleanup_data_directory", return_value=active), patch.object(
                runtime_bridge,
                "active_data_directory",
                side_effect=AssertionError("routed sidecar run polling must not rehash the bundle"),
            ):
                runtime_bridge.store_for_payload(trusted)

            payload["surface"] = "backend"
            with self.assertRaisesRegex(runtime_bridge.RuntimeBridgeError, "Core sidecar surface"):
                runtime_bridge.trusted_sidecar_runtime_metadata_payload(payload)

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

    def test_legacy_correlation_schema_upgrades_with_empty_terminal_event_id(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            with patch.object(runtime_bridge, "active_data_directory", return_value=active):
                record, _ = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_legacy_schema",
                    conversation_id="od_conversation_legacy_schema",
                    assistant_message_id="od_message_legacy_schema",
                    client_request_id="client-legacy-schema",
                    agent_id="maverick",
                )
                path = active / runtime_bridge.BRIDGE_DIRECTORY / runtime_bridge.CORRELATIONS_FILE
                records = json.loads(path.read_text(encoding="utf-8"))
                records[0]["schema_version"] = runtime_bridge.LEGACY_BRIDGE_SCHEMA_VERSION
                records[0].pop("terminal_runtime_event_id")
                path.write_text(json.dumps(records), encoding="utf-8")

                store = runtime_bridge.store_for_payload(payload)
                migrated = store.get(record["od_run_id"])
                store.update(record["od_run_id"], lambda current: current)
                persisted = json.loads(path.read_text(encoding="utf-8"))[0]

            self.assertEqual(migrated["schema_version"], runtime_bridge.BRIDGE_SCHEMA_VERSION)
            self.assertEqual(migrated["terminal_runtime_event_id"], "")
            self.assertEqual(persisted["schema_version"], runtime_bridge.BRIDGE_SCHEMA_VERSION)
            self.assertEqual(persisted["terminal_runtime_event_id"], "")

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
                        runtime_event_id=f"runtime-event-{suffix}",
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
                    runtime_event_id="runtime-event-cancel-race",
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
                    runtime_event_id="runtime-event-terminal-success",
                    files=[],
                )
                preserved = runtime_bridge.record_terminal(
                    payload,
                    runtime_session_id="session-terminal-race",
                    turn_id="turn-terminal-race",
                    event_type="runtime.turn.failed",
                    runtime_event_id="runtime-event-terminal-failure",
                    files=[],
                )

            self.assertIsNotNone(terminal)
            self.assertEqual(terminal["status"], "canceled")
            self.assertEqual(terminal["error"], "")
            self.assertEqual(translated["sse_events"][0]["data"]["status"], "canceled")
            self.assertIsNotNone(preserved)
            self.assertEqual(preserved["status"], "succeeded")
            self.assertEqual(preserved["result_package"]["run"]["status"], "succeeded")

    def test_terminal_runtime_event_replay_skips_opendesign_and_persistence_mutations(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            with patch.object(runtime_bridge, "active_data_directory", return_value=active):
                record, _ = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_event_replay",
                    conversation_id="od_conversation_event_replay",
                    assistant_message_id="od_message_event_replay",
                    client_request_id="client-event-replay",
                    agent_id="maverick",
                )
                runtime_bridge.record_submission(
                    payload,
                    {
                        "od_run_id": record["od_run_id"],
                        "runtime_request_status": "submitted",
                        "runtime_session_id": "session-event-replay",
                        "turn_id": "turn-event-replay",
                        "stream_id": "stream-event-replay",
                    },
                )
                arguments = {
                    "runtime_session_id": "session-event-replay",
                    "turn_id": "turn-event-replay",
                    "runtime_event_id": "runtime-event-replay",
                }
                with patch.object(
                    service,
                    "_opendesign_json_request",
                    return_value={"files": [{"name": "index.html"}]},
                ) as opendesign_request, patch.object(service, "_opendesign_put", return_value={"message": {}}) as message_update:
                    first = service.runtime_bridge_terminal(
                        payload,
                        {**arguments, "output_text": "Finished design"},
                        event_type="runtime.turn.completed",
                    )
                    replayed = service.runtime_bridge_terminal(
                        payload,
                        arguments,
                        event_type="runtime.turn.completed",
                    )

                persisted = runtime_bridge.store_for_payload(payload).get(record["od_run_id"])

            opendesign_request.assert_called_once()
            message_update.assert_called_once()
            self.assertEqual(message_update.call_args.args[2]["content"], "Finished design")
            self.assertEqual(replayed, first)
            self.assertEqual(persisted["terminal_runtime_event_id"], "runtime-event-replay")

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
                    "deleted_conversation_bindings": 1,
                },
            )
            self.assertEqual([record["od_run_id"] for record in remaining], [records["retained"]["od_run_id"]])

            with self.assertRaisesRegex(service.DesignStudioError, "trusted platform cleanup flow"):
                service.dispatch(
                    "runtime.cleanup_sessions",
                    self._payload(root),
                    {"runtime_session_ids": ["session-retained"]},
                )

    def test_conversation_binding_migrates_latest_session_and_is_reused(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            with patch.object(runtime_bridge, "active_data_directory", return_value=active):
                older, _ = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_bound",
                    conversation_id="od_conversation_bound",
                    assistant_message_id="od_message_old",
                    client_request_id="client-old",
                    agent_id="maverick",
                )
                runtime_bridge.record_submission(
                    payload,
                    {
                        "od_run_id": older["od_run_id"],
                        "runtime_request_status": "submitted",
                        "runtime_session_id": "session-old",
                        "turn_id": "turn-old",
                        "stream_id": "stream-old",
                    },
                )
                binding_path = active / runtime_bridge.BRIDGE_DIRECTORY / runtime_bridge.BINDINGS_FILE
                binding_path.unlink()
                newer, _ = runtime_bridge.reserve_run(
                    payload,
                    project_id="od_project_bound",
                    conversation_id="od_conversation_bound",
                    assistant_message_id="od_message_new",
                    client_request_id="client-new",
                    agent_id="maverick",
                )
                runtime_bridge.store_for_payload(payload).update(
                    newer["od_run_id"],
                    lambda record: {
                        **record,
                        "runtime_session_id": "session-new",
                        "turn_id": "turn-new",
                        "stream_id": "stream-new",
                        "updated_at": "2099-01-01T00:00:00+00:00",
                    },
                )
                migrated = runtime_bridge.binding_store_for_payload(payload).get(
                    "default", "od_project_bound", "od_conversation_bound"
                )

            self.assertIsNotNone(migrated)
            self.assertEqual(migrated["runtime_session_id"], "session-new")
            self.assertEqual(migrated["thread_id"], "session-new")

    def test_second_run_for_conversation_reuses_maverick_runtime_session(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            (root / "project").mkdir()
            payload = self._payload(root)

            def opendesign_response(_payload, path):
                if path.endswith("/conversations"):
                    return {"conversations": [{"id": "od_conversation_reuse"}]}
                return {"project": {"id": "od_project_reuse", "name": "Reuse"}}

            with patch.object(runtime_bridge, "active_data_directory", return_value=active), patch.object(
                service, "_opendesign_request", side_effect=opendesign_response
            ), patch.object(service, "project_root_relative_to_app_data", return_value="opendesign/project"):
                first = service._create_runtime_bridge_run(
                    payload,
                    {
                        "projectId": "od_project_reuse",
                        "conversationId": "od_conversation_reuse",
                        "assistantMessageId": "od_message_first",
                        "clientRequestId": "client-first",
                        "message": "First turn",
                    },
                )
                first_request = first["runtime_session_requests"][0]
                self.assertNotIn("runtime_session_id", first_request)
                runtime_bridge.record_submission(
                    payload,
                    {
                        "od_run_id": first["json"]["runId"],
                        "runtime_request_status": "submitted",
                        "runtime_session_id": "session-reused",
                        "turn_id": "turn-first",
                        "stream_id": "stream-first",
                    },
                )
                second = service._create_runtime_bridge_run(
                    payload,
                    {
                        "projectId": "od_project_reuse",
                        "conversationId": "od_conversation_reuse",
                        "assistantMessageId": "od_message_second",
                        "clientRequestId": "client-second",
                        "message": "Second turn",
                    },
                )

            self.assertEqual(second["runtime_session_requests"][0]["runtime_session_id"], "session-reused")
            self.assertEqual(second["runtime_session_requests"][0]["result_visibility"], "internal")

    def test_floating_chat_submit_writes_canonical_messages_and_requests_public_runtime_result(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            payload = self._payload(root)
            messages = []

            def opendesign_response(_payload, path):
                if path.endswith("/conversations"):
                    return {"conversations": [{"id": "od_conversation_chat"}]}
                return {"project": {"id": "od_project_chat", "name": "Chat project"}}

            def upsert(_payload, project_id, conversation_id, message_id, body):
                messages.append((project_id, conversation_id, message_id, body))
                return {"message": body}

            with patch.object(runtime_bridge, "active_data_directory", return_value=active), patch.object(
                service, "_opendesign_request", side_effect=opendesign_response
            ), patch.object(service, "_upsert_opendesign_message", side_effect=upsert), patch.object(
                service, "project_root_relative_to_app_data", return_value="opendesign/project"
            ):
                result = service.chat_submit_turn(
                    payload,
                    {
                        "od_project_id": "od_project_chat",
                        "od_conversation_id": "od_conversation_chat",
                        "input_text": "Build the hero",
                        "client_message_id": "client-floating-chat",
                        "session_mode": "plan",
                        "attachments": [
                            {
                                "workspace_relative_path": "storage/uploaded/reference.png",
                                "name": "reference.png",
                                "size_bytes": 42,
                                "content_type": "image/png",
                            }
                        ],
                    },
                )

            self.assertEqual([item[3]["role"] for item in messages], ["user", "assistant"])
            self.assertEqual(messages[0][3]["content"], "Build the hero")
            request = result["runtime_session_requests"][0]
            self.assertEqual(request["result_visibility"], "public")
            self.assertEqual(request["attachments"][0]["workspace_relative_path"], "storage/uploaded/reference.png")
            self.assertIn("session mode is plan", request["system_prompt"])
            self.assertEqual(result["json"]["source_app_id"], "design-studio")
            self.assertEqual(result["json"]["od_conversation_id"], "od_conversation_chat")

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
