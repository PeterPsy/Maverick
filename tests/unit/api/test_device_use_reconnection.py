from dataclasses import asdict, replace
from datetime import UTC, datetime
import queue
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT, DEVICE_USE_PROTOCOL_VERSION, DEVICE_USE_TOOL_CONTRACT_DIGEST,
)
from core.device_use.runtime_registry import device_use_service_for_session, unregister_device_use_session
from core.device_use.service import DeviceUseService
from core.providers.agentic_workspace_admin import configure_workspace_agentic_default
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.agentic_runtime_service import update_runtime_provider_state
from core.runtime.device_use_continuation_context import device_use_continuation_context
from core.runtime.provider_input_capture_context import capture_runtime_provider_input
from core.runtime.runtime_process_lifecycle import release_idle_runtime_processes
from core.runtime.runtime_idle_deadlines import runtime_idle_deadlines
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.runtime_session import runtime_session_from_document
from core.runtime.runtime_threads import create_runtime_thread
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class DeviceUseReconnectionTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_retired_limited_lease_loads_as_off_without_losing_chat_authority(self):
        document = asdict(self.before)
        document["device_use_binding"]["mode"] = "on"
        retired = runtime_session_from_document(document)
        self.assertIsNone(retired.device_use_binding)
        self.assertEqual(retired.execution_binding, self.before.execution_binding)
        self.assertEqual(retired.session_id, self.before.session_id)
        self.state.runtime_store.save_session(retired)
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual((status, payload["error"]), (403, "device_use_session_forbidden"))

    def test_reviewed_v51_full_only_upgrade_retires_old_context(self):
        old = replace(self.before.device_use_binding, executor_contract="macos-v51",
                      tool_contract_digest="de5800e0240474b5108e40f3d35c0aa78532743949d9d8696a6ac43505762c76")
        self.state.runtime_store.save_session(replace(self.before, device_use_binding=old))
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual(status, 200, payload)
        current = self.state.runtime_store.get_session(self.session_id)
        self.assertEqual(current.device_use_binding.mode, "full")
        self.assertEqual(current.device_use_binding.executor_contract, DEVICE_USE_EXECUTOR_CONTRACT)
        self.assertEqual(current.execution_binding, self.before.execution_binding)

    def test_reviewed_v49_efficiency_upgrade_retires_old_context(self):
        old = replace(self.before.device_use_binding, executor_contract="macos-v49",
                      tool_contract_digest="eb8c2b9ca42c9c03ee516283fd39490d1ca5957d89c665bade60c126a1169abf")
        self.state.runtime_store.save_session(replace(self.before, device_use_binding=old))
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual(status, 200, payload)
        current = self.state.runtime_store.get_session(self.session_id)
        self.assertEqual(current.device_use_binding.executor_contract, DEVICE_USE_EXECUTOR_CONTRACT)
        self.assertEqual(current.execution_binding, self.before.execution_binding)
        self.assertEqual(current.device_use_binding.mode, old.mode)

    def test_reviewed_v48_coding_upgrade_retires_old_context(self):
        old = replace(self.before.device_use_binding, executor_contract="macos-v48",
                      tool_contract_digest="5682ddabb352ada6e227e2294e8026ae3f47ce095e3de9466aab11627d6a5b8d")
        self.state.runtime_store.save_session(replace(self.before, device_use_binding=old))
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual(status, 200, payload)
        current = self.state.runtime_store.get_session(self.session_id)
        self.assertEqual(current.device_use_binding.executor_contract, DEVICE_USE_EXECUTOR_CONTRACT)
        self.assertEqual(current.execution_binding, self.before.execution_binding)

    def test_reviewed_v46_repair_upgrade_retires_old_context(self):
        old = replace(self.before.device_use_binding, executor_contract="macos-v46",
                      tool_contract_digest="776dd4eeb79c7eca35ddda4475d6c412401987cebdd1f14fab34d1ef5345c7fb")
        self.state.runtime_store.save_session(replace(self.before, device_use_binding=old))
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual(status, 200, payload)
        current = self.state.runtime_store.get_session(self.session_id)
        self.assertEqual(current.device_use_binding.executor_contract, DEVICE_USE_EXECUTOR_CONTRACT)

    def test_reviewed_v45_companion_upgrade_retires_context_and_preserves_authority(self):
        old = replace(self.before.device_use_binding, executor_contract="macos-v45",
                      tool_contract_digest="0b96e1a3013c1bfece055623d8b104cd029b1b8ebb21719686999531abbf424d")
        self.state.runtime_store.save_session(replace(self.before, device_use_binding=old))
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual(status, 200, payload)
        current = self.state.runtime_store.get_session(self.session_id)
        self.assertEqual(current.device_use_binding.executor_contract, DEVICE_USE_EXECUTOR_CONTRACT)
        self.assertEqual(current.device_use_binding.mode, old.mode)
        self.assertEqual(current.execution_binding, self.before.execution_binding)

    def test_reviewed_v44_upgrade_renews_existing_chat_without_changing_authority(self):
        old = replace(self.before.device_use_binding, executor_contract="macos-v44",
                      tool_contract_digest="d525d61fc31a5d873b189166be26d90bd613dc1e2e430f69a07744d920ea4dd1")
        self.state.runtime_store.save_session(replace(self.before, device_use_binding=old))
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual(status, 200, payload)
        current = self.state.runtime_store.get_session(self.session_id)
        self.assertEqual(current.device_use_binding.executor_contract, DEVICE_USE_EXECUTOR_CONTRACT)
        self.assertEqual(current.execution_binding, self.before.execution_binding)

    def test_unknown_contract_upgrade_is_rejected(self):
        old = replace(self.before.device_use_binding, executor_contract="macos-v43", tool_contract_digest="unknown")
        self.state.runtime_store.save_session(replace(self.before, device_use_binding=old))
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual((status, payload["error"]), (409, "device_use_reconnect_scope_changed"))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = self._repo_root(temporary.name)
        self.root = root
        with patch.dict("os.environ", {
            "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
            "MAVERICK_ADMIN_USERNAME": "admin", "MAVERICK_ADMIN_PASSWORD": "maverick",
        }):
            self.state = bootstrap_platform_state(start_path=root)
        profile = configure_workspace_agentic_default(
            self.state.provider_store, self.state.provider_registry, workspace_id="default",
            provider_id="codex", model_id="gpt-5.6-sol", model_reasoning_effort="max",
        )
        self.app = PlatformHost(self.state, start_path=root)
        self.cookie = self._login(self.app)
        self.original = self._ready_activation()
        with patch("core.api.runtime_api._prewarm_new_runtime_session", return_value=None):
            status, session, _ = self._invoke(
                self.app, path="/api/runtime/sessions", method="POST", cookie=self.cookie,
                body={
                    "agent_id": "chat", "source_app_id": "chat", "runtime_mode": "agentic",
                    "workspace_profile_binding_id": profile.binding_id,
                    "device_use_activation_id": self.original["activation_id"],
                },
            )
        self.assertEqual(status, 201, session)
        self.addCleanup(runtime_idle_deadlines.cancel_owner, self.state)
        self.session_id = session["session_id"]
        self.addCleanup(unregister_device_use_session, self.session_id)
        self.before = self.state.runtime_store.get_session(self.session_id)

    def _ready_activation(self, *, mode="full", apps=None, initial_app="com.apple.Safari", cookie=None):
        status, activation, _ = self._invoke(
            self.app, path="/api/device-use/activations", method="POST",
            body={"client_generation": "reconnected-window"}, cookie=cookie or self.cookie,
        )
        self.assertEqual(status, 201, activation)
        self.state.device_use_service.connect_executor(
            ticket=activation["ticket"], protocol_version=DEVICE_USE_PROTOCOL_VERSION,
            executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
            tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST, mode=mode,
            initial_app=initial_app, approved_apps=apps or ["com.apple.Safari"],
            outbound=queue.Queue(maxsize=8),
        )
        return activation

    def _reconnect(self, activation, *, previous=None, cookie=None):
        return self._invoke(
            self.app, path=f"/api/device-use/sessions/{self.session_id}/reconnect",
            method="POST", cookie=cookie or self.cookie,
            body={"activation_id": activation["activation_id"],
                  "previous_activation_id": previous or self.original["activation_id"]},
        )[:2]

    def _turn(self, status):
        now = datetime.now(UTC)
        turn = RuntimeTurnRecord(
            turn_id="preserved-turn", session_id=self.session_id, workspace_id="default",
            status=status, input_text="Continua il montaggio", created_at=now, updated_at=now,
            started_at=now, completed_at=now if status == "completed" else None, failure_reason=None,
        )
        self.state.runtime_store.save_turn(turn)
        return turn

    def test_reconnect_after_core_restart_preserves_session_pin_and_history(self):
        turn = self._turn("completed")
        self.state = replace(self.state, device_use_service=DeviceUseService())
        self.app = PlatformHost(self.state, start_path=self.root)
        unregister_device_use_session(self.session_id)
        status, missing, _ = self._invoke(
            self.app, path=f"/api/device-use/activations/{self.original['activation_id']}",
            cookie=self.cookie,
        )
        self.assertEqual((status, missing["error"]), (409, "device_use_activation_not_found"))
        activation = self._ready_activation()
        status, public = self._reconnect(activation)
        self.assertEqual(status, 200, public)
        self.assertTrue(public["ready"])
        self.assertTrue(public["bound"])
        self.assertNotIn("ticket", public)
        self.assertNotIn("approved_apps", public)
        after = self.state.runtime_store.get_session(self.session_id)
        self.assertEqual(after, replace(self.before, device_use_binding=after.device_use_binding))
        self.assertEqual(after.device_use_binding.activation_id, activation["activation_id"])
        self.assertEqual(self.state.runtime_store.list_turns(self.session_id), [turn])
        self.assertIs(device_use_service_for_session(self.session_id), self.state.device_use_service)
        self.assertEqual(self.state.device_use_service.binding_snapshot(
            activation["activation_id"], owner_user_id="user:admin", workspace_id="default",
            bound_session_id=self.session_id,
        ), after.device_use_binding)

    def test_explicit_reactivation_after_off_works_in_same_conversation(self):
        self.state.device_use_service.stop_activation(self.original["activation_id"], reason="stopped_by_user")
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["mode"], "full")

    def test_reconnect_publishes_the_new_binding_to_other_thread_views(self):
        create_runtime_thread(
            self.state.runtime_store, workspace_id="default", runtime_session_id=self.session_id,
            thread_id=self.session_id, agent_label="chat", source_app_id="chat",
        )
        activation = self._ready_activation()
        with patch.object(self.state.runtime_thread_event_bus, "publish") as publish:
            status, payload = self._reconnect(activation)
        self.assertEqual(status, 200, payload)
        event = publish.call_args.kwargs
        self.assertEqual(event["workspace_id"], "default")
        self.assertEqual(event["event"]["thread"]["device_use"], {
            "activation_id": activation["activation_id"], "mode": "full",
        })

    def test_active_and_queued_turns_cannot_be_rebound(self):
        for turn_status in ("active", "queued", "waiting_for_tool_confirmation"):
            with self.subTest(status=turn_status):
                self._turn(turn_status)
                activation = self._ready_activation()
                with patch("core.api.device_use_reconnection.release_idle_runtime_processes") as close:
                    status, payload = self._reconnect(activation)
                self.assertEqual((status, payload["error"]), (409, "device_use_session_busy"))
                close.assert_not_called()
                self.assertEqual(self.state.runtime_store.get_session(self.session_id), self.before)

    def test_running_app_discovery_changes_do_not_change_full_authority(self):
        for options in (
            {"apps": ["com.apple.Safari", "com.apple.Notes"]},
            {"initial_app": "com.apple.Notes", "apps": ["com.apple.Notes"]},
        ):
            with self.subTest(options=options):
                self.state.runtime_store.save_session(self.before)
                status, payload = self._reconnect(self._ready_activation(**options))
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["mode"], "full")

    def test_stale_reconnect_cannot_replace_a_newer_lease(self):
        first = self._ready_activation()
        self.assertEqual(self._reconnect(first)[0], 200)
        after = self.state.runtime_store.get_session(self.session_id)
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual((status, payload["error"]), (409, "device_use_binding_changed"))
        self.assertEqual(self.state.runtime_store.get_session(self.session_id), after)

    def test_activation_must_belong_to_the_current_login(self):
        activation = self._ready_activation()
        status, payload = self._reconnect(activation, cookie=self._login(self.app))
        self.assertEqual((status, payload["error"]), (403, "device_use_activation_forbidden"))

    def test_foreign_or_ordinary_chat_cannot_be_converted_to_device_use(self):
        for updates in ({"owner_user_id": "other-user"}, {"device_use_binding": None}):
            with self.subTest(updates=updates):
                self.state.runtime_store.save_session(replace(self.before, **updates))
                status, payload = self._reconnect(self._ready_activation())
                self.assertEqual((status, payload["error"]), (403, "device_use_session_forbidden"))
        self.state.runtime_store.save_session(self.before)

    def test_store_cas_failure_revokes_the_unpersisted_new_lease(self):
        activation = self._ready_activation()
        with patch.object(self.state.runtime_store, "replace_session_device_use_lease",
                          side_effect=RuntimeProviderStateError("device_use_binding_changed")):
            status, payload = self._reconnect(activation)
        self.assertEqual((status, payload["error"]), (409, "device_use_binding_changed"))
        public = self.state.device_use_service.public_activation(
            activation["activation_id"], owner_user_id="user:admin", workspace_id="default",
        )
        self.assertFalse(public["ready"])
        self.assertEqual(public["status"], "stopped")
        self.assertEqual(self.state.runtime_store.get_session(self.session_id), self.before)

    def test_connected_ephemeral_provider_is_not_reaped_between_turns(self):
        self._turn("completed")
        with patch("core.runtime.runtime_process_lifecycle._schedule_idle_runtime_process_reap") as schedule:
            release_idle_runtime_processes(
                self.state, session_id=self.session_id, provider_id="codex", reason="turn_completed",
            )
        schedule.assert_not_called()
        self.state.device_use_service.disconnect_executor(self.original["activation_id"])
        with patch("core.runtime.runtime_process_lifecycle._schedule_idle_runtime_process_reap") as schedule:
            release_idle_runtime_processes(
                self.state, session_id=self.session_id, provider_id="codex", reason="turn_completed",
            )
        schedule.assert_called_once()

    def test_retained_context_is_rechecked_and_closed_after_disconnect(self):
        self._turn("completed")
        with (
            patch("core.runtime.runtime_process_lifecycle.runtime_idle_deadlines.schedule") as schedule,
            patch("core.runtime.runtime_process_lifecycle.runtime_idle_deadlines.pending", return_value=False),
            patch("core.runtime.runtime_process_lifecycle._release_idle_runtime_processes_now", return_value=1) as close,
        ):
            release_idle_runtime_processes(
                self.state, session_id=self.session_id, provider_id="codex", reason="turn_completed",
            )
            callback = schedule.call_args.args[4]
            self.assertEqual(schedule.call_args.args[2], "device-use-reap")
            callback()
            close.assert_not_called()
            self.assertEqual(schedule.call_count, 2)
            self.state.device_use_service.disconnect_executor(self.original["activation_id"])
            callback()
            close.assert_called_once()

    def test_reconnection_rebuilds_governed_text_context_without_resuming_the_old_archive(self):
        self._turn("completed")
        update_runtime_provider_state(self.state.runtime_store, session_id=self.session_id, updates={
            "provider_thread_id": "old-ephemeral-thread", "continuation_id": "old-continuation",
        })
        status, payload = self._reconnect(self._ready_activation())
        self.assertEqual(status, 200, payload)
        provider_state = self.state.runtime_store.get_provider_state(self.session_id)
        self.assertIsNone(provider_state.provider_thread_id)
        self.assertIsNone(provider_state.continuation_id)
        session = self.state.runtime_store.get_session(self.session_id)
        now = datetime.now(UTC)
        current = RuntimeTurnRecord(
            turn_id="new-turn", session_id=self.session_id, workspace_id="default", status="active",
            input_text="Riprendi", created_at=now, updated_at=now, started_at=now,
            completed_at=None, failure_reason=None,
        )
        self.state.runtime_store.save_turn(current)
        captured = capture_runtime_provider_input(
            self.state, session=session, turn_id=current.turn_id, input_text=current.input_text,
            app_references=None, attachments=None,
        )
        self.assertIn("Continua il montaggio", captured.input_text)
        self.assertIn("Do not replay previous tool calls", captured.input_text)
        self.assertTrue(captured.input_text.endswith("[Current user input]\nRiprendi"))
        source = next(source for source in captured.sources if source.source_id == "device-use-continuation")
        self.assertEqual(source.provenance, "provider_state")
        self.assertIsNotNone(source.classification)
        manifest = self.state.runtime_store.get_turn(current.turn_id).provider_input_classification_manifest
        self.assertIn("device-use-continuation", str(manifest))
        self.state.runtime_store.save_turn(replace(current, status="completed", completed_at=now))
        self.assertIsNone(device_use_continuation_context(self.state, session=session, turn_id="following-turn"))
