"""Exercise real JSON-RPC, private output, images and bounded operator runs."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.device_use.models import DeviceUseResult
from core.providers.codex_computer_actor import CodexComputerActor


class CodexComputerActorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "auth.json").write_text('{}')
        self.validate = patch("core.providers.codex_computer_actor.CodexProviderAdapter.validate_model_settings")
        self.home = patch("core.providers.codex_computer_actor.CodexProviderAdapter._source_codex_home", return_value=root)
        self.launch = patch("core.providers.codex_computer_actor.CodexProviderAdapter._build_command", return_value=["fixture"])
        self.validate_mock = self.validate.start()
        self.home.start()
        self.launch_mock = self.launch.start()
        self.actor = self.make_actor()
        self.calls = []
        self.usage = []

    def make_actor(self, selection=None):
        server = Path(__file__).resolve().parents[2] / "support" / "computer_actor_server.py"
        return CodexComputerActor(
            SimpleNamespace(session_id="actor-test", workspace_id="default", runtime_root=self.temp.name),
            SimpleNamespace(mode="full", approved_apps=("com.apple.Safari",), initial_app="com.apple.Safari"),
            selection=selection,
            command_runner=lambda _command, **kwargs: subprocess.Popen([sys.executable, "-I", "-u", str(server)], **kwargs),
        )

    def tearDown(self):
        self.actor.close()
        self.home.stop()
        self.launch.stop()
        self.validate.stop()
        self.temp.cleanup()

    def invoke(self, tool, arguments, call_id):
        self.calls.append((tool, arguments, call_id))
        return DeviceUseResult("invocation", call_id, {"success": True, "contentItems": [
            {"type": "inputText", "text": "native result"}]},
            b"fresh-jpeg" if arguments["action"] == "observe_app" else None, None, 1.0)

    def run_actor(self, mode="normal", **kwargs):
        return self.actor.run({"objective": mode, "completion_criterion": "Verify target", "constraints": ""},
            invoke=self.invoke, active=lambda: True, usage_sink=self.usage.append, **kwargs)

    def test_multiple_verified_steps_return_only_final_result_and_image(self):
        output, jpeg = self.run_actor()
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["steps"], 3)
        self.assertEqual([call[1]["action"] for call in self.calls], ["observe_app", "click", "observe_app"])
        self.assertEqual(jpeg, b"fresh-jpeg")
        self.assertNotIn("PRIVATE_ACTOR", json.dumps(output))
        self.assertTrue(all(item["model_id"] == "gpt-6.1-sol" for item in self.usage))
        self.assertTrue(all(item["context_tokens"] is None for item in self.usage))

    def test_selected_model_and_effort_reach_protocol_and_usage(self):
        self.actor.close()
        self.actor = self.make_actor(SimpleNamespace(model_id="gpt-6-sol", reasoning_effort="medium"))
        self.validate_mock.assert_called_with("gpt-6-sol", "medium")
        output, _ = self.run_actor()
        self.assertEqual(output["status"], "completed")
        self.assertTrue(self.usage)
        self.assertTrue(all(item["model_id"] == "gpt-6-sol" for item in self.usage))

    def test_images_and_receipts_are_injected_together_without_steering(self):
        output, _ = self.run_actor('paired-image')
        self.assertEqual(output['status'], 'completed')

    def test_native_target_lines_are_injected_verbatim_with_the_image(self):
        self.invoke = lambda tool, arguments, call_id: DeviceUseResult(
            'invocation', call_id, {'success': True, 'contentItems': [
                {'type': 'inputText', 'text': 'snapshot=ps1_current\nelem_72 - button - Seven\nelem_73 - button - Eight'}]},
            b'fresh-jpeg', None, 1.0)
        output, _ = self.run_actor('multiline-receipt')
        self.assertEqual(output['status'], 'completed')

    def test_failed_image_injection_stops_before_native_input(self):
        output, _ = self.run_actor('image-injection-failure')
        self.assertEqual(output['status'], 'blocked')
        self.assertEqual(output['summary'], 'computer_actor_execution_interrupted')
        self.assertEqual([call[1]['action'] for call in self.calls], ['observe_app'])

    def test_partial_progress_cannot_be_reported_as_completed(self):
        output, _ = self.run_actor('partial')
        self.assertEqual(output['status'], 'needs_decision')
        self.assertEqual(output['summary'], 'computer_actor_criterion_not_met')
        self.assertNotIn('completion_criterion_met', output)

    def test_process_is_confined_to_private_operator_filesystem(self):
        scope = self.launch_mock.call_args.kwargs
        self.assertEqual(scope["execution_mode"], "sandbox")
        self.assertTrue(scope["require_code_mode_host"])
        self.assertEqual(scope["workspace_root"].parent, scope["runtime_root"])
        self.assertEqual(scope["runtime_root"].name, "computer-actor")
        self.assertEqual((scope["runtime_home"] / "auth.json").stat().st_mode & 0o777, 0o600)

    def test_process_is_reused_but_each_task_gets_an_independent_usage_stream(self):
        pid = self.actor.process.pid
        self.run_actor()
        first_source = self.usage[-1]["source"]
        self.run_actor()
        self.assertEqual(self.actor.process.pid, pid)
        self.assertNotEqual(first_source, self.usage[-1]["source"])

    def test_step_budget_stops_before_the_next_input(self):
        output, _jpeg = self.run_actor(max_steps=1)
        self.assertEqual(output["summary"], "computer_actor_step_budget")
        self.assertEqual(len(self.calls), 1)

    def test_context_checkpoint_releases_old_images_and_next_task_can_run(self):
        output, _ = self.run_actor(max_observations=1)
        self.assertEqual(output['summary'], 'computer_actor_context_checkpoint')
        self.calls.clear()
        output, _ = self.run_actor()
        self.assertEqual(output['status'], 'completed')
        self.assertEqual(len(self.calls), 3)

    def test_semantic_action_before_observation_recovers_without_input(self):
        output, _ = self.run_actor('semantic-before-observation')
        self.assertEqual(output['status'], 'completed')
        self.assertEqual([call[1]['action'] for call in self.calls], ['observe_app', 'click', 'observe_app'])

    def test_repeated_semantic_validation_errors_are_bounded(self):
        output, _ = self.run_actor('semantic-rejection-limit')
        self.assertEqual(output['status'], 'needs_decision')
        self.assertEqual(output['summary'], 'computer_actor_fresh_observation_required')
        self.assertEqual(self.calls, [])

    def test_planned_detail_is_preserved_at_the_native_boundary(self):
        def invoke(tool, arguments, call_id):
            self.calls.append((tool, arguments, call_id))
            text = 'snapshot=ps1_current; bundle_id=com.apple.Safari; window_id=42\n'
            if arguments.get('action') == 'click':
                text += 'AXStaticText (1 found):\n  elem_2 - "Submitted" - value: "Submitted"\n'
            elif arguments.get('details') is True:
                text += 'AXButton (1 found):\n  elem_1 - "Submit"\n'
            else:
                text += 'Warning: AX tree truncated at depth 8.\n'
            return DeviceUseResult('fixture', call_id, {'success': True, 'contentItems': [
                {'type': 'inputText', 'text': text}]}, b'fresh-jpeg', None, 1)

        output, _ = self.actor.run({'objective': 'planned-detail', 'completion_criterion': 'Submitted',
            'steps': [{'tool': 'mac_peekaboo', 'target': 'com.apple.Safari', 'window_id': 42,
                       'action': 'click', 'control': {'label': 'Submit'}, 'expect': {'text': 'Submitted'}}]},
            invoke=invoke, active=lambda: True, usage_sink=self.usage.append)
        self.assertEqual(output['status'], 'completed')
        self.assertEqual([call[1]['action'] for call in self.calls], ['observe', 'observe', 'click'])
        self.assertTrue(all(call[1]['details'] for call in self.calls))

    def test_planned_task_rejects_raw_input_without_dispatch(self):
        output, _ = self.actor.run({'objective': 'normal', 'completion_criterion': 'Submitted',
            'steps': [{'tool': 'mac_peekaboo', 'target': 'com.apple.Safari', 'action': 'click',
                       'control': {'label': 'Submit'}, 'expect': {'text': 'Submitted'}}]},
            invoke=self.invoke, active=lambda: True, usage_sink=self.usage.append)
        self.assertEqual(output['summary'], 'computer_actor_criterion_not_met')
        self.assertEqual([call[1]['action'] for call in self.calls], ['observe_app', 'observe_app'])

    def test_root_can_read_after_a_delegation_failure_without_replaying_input(self):
        from core.device_use.computer_actor_contract import planner_device_use_tools
        native = self.invoke
        def invoke(tool, args, call_id):
            if tool == 'computer_interact':
                return DeviceUseResult('delegate', call_id, {'success': False, 'contentItems': [
                    {'type': 'inputText', 'text': 'Operator could not verify the effect; inspect before continuing.'}]}, None, None, 1)
            return native(tool, args, call_id)
        self.invoke = invoke
        result, _ = self.run_actor('root-delegation-failure', tools=planner_device_use_tools())
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([call[1]['action'] for call in self.calls], ['observe_app', 'observe_app'])

    def test_interrupted_task_does_not_leak_queued_events_into_the_next_task(self):
        first, _ = self.run_actor(max_steps=1)
        self.assertEqual(first["status"], "needs_decision")
        self.actor.transport.events.put({"kind": "completed", "status": "completed",
                                         "thread_id": "operator-thread-1"})
        second, _ = self.run_actor()
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["steps"], 3)

    def test_content_and_code_tools_are_denied_without_dispatch(self):
        output, _jpeg = self.run_actor("forbidden")
        self.assertEqual(output["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_completion_without_final_visual_evidence_is_not_accepted(self):
        self.invoke = lambda tool, arguments, call_id: DeviceUseResult(
            "invocation", call_id, {"success": True}, None, None, 1.0)
        output, _jpeg = self.run_actor()
        self.assertEqual(output["summary"], "computer_actor_completion_unverified")

    def test_malformed_output_is_a_decision_needed(self):
        output, _jpeg = self.run_actor("invalid")
        self.assertEqual(output["status"], "needs_decision")

    def browser_invoke(self, tool, arguments, call_id):
        self.calls.append((tool, arguments, call_id))
        text = json.dumps({"execution_environment": "parallel_companion", "tabs_complete": True,
                           "tabs": [{"tab_id": "remaining"}]})
        return DeviceUseResult("invocation", call_id, {"success": True, "contentItems": [
            {"type": "inputText", "text": text}]},
            b"fresh-browser" if arguments["action"] == "observe" else None, None, 1.0)

    def test_closed_tab_inventory_is_verified_completion_without_final_image(self):
        self.invoke = self.browser_invoke
        output, jpeg = self.run_actor("browser-close")
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["evidence"], "Native tab inventory excludes the closed tab.")
        self.assertIsNone(jpeg)
        self.assertEqual([call[1]["action"] for call in self.calls], ["observe", "close_tab", "list_tabs"])

    def test_unverified_completion_retains_observed_evidence_for_the_planner(self):
        self.invoke = lambda tool, args, cid: DeviceUseResult("test", cid, {"success": True}, None, None, 1)
        output, _ = self.run_actor("browser-close")
        self.assertEqual(output["status"], "needs_decision")
        self.assertEqual(output["evidence"], "Native tab inventory excludes the closed tab.")

    def test_uncertain_tab_closure_is_verified_by_inventory_without_replay(self):
        self.invoke = self.browser_invoke
        self.fail_native_call(2, "MC-COMPANION-04")
        output, jpeg = self.run_actor("browser-close-recovery")
        self.assertEqual(output["status"], "completed")
        self.assertIsNone(jpeg)
        self.assertIn("MC-COMPANION-04", output["evidence"])
        self.assertEqual([call[1]["action"] for call in self.calls], ["observe", "close_tab", "list_tabs"])

    def test_companion_uncertainty_observes_same_tab_and_never_replays_return(self):
        self.invoke = self.browser_invoke
        self.fail_native_call(2, "MC-COMPANION-04")
        output, jpeg = self.run_actor("browser-recovery")
        self.assertEqual(output["status"], "completed")
        self.assertEqual(jpeg, b"fresh-browser")
        self.assertIn("MC-COMPANION-04", output["evidence"])
        self.assertEqual([call[1]["action"] for call in self.calls], ["observe", "keypress", "observe", "scroll", "observe"])

    def test_companion_recovery_blocks_other_tabs_and_return_with_a_new_receipt(self):
        for mode, count in (("browser-replay", 3), ("browser-other-tab", 2)):
            with self.subTest(mode=mode):
                self.calls.clear()
                self.invoke = self.browser_invoke
                self.fail_native_call(2, "MC-COMPANION-04")
                output, _ = self.run_actor(mode)
                self.assertEqual(output["summary"], "computer_actor_recovery_action_denied")
                self.assertEqual(len(self.calls), count)

    def test_timeout_does_not_dispatch_or_retry_native_input(self):
        output, _jpeg = self.run_actor("wait", timeout_seconds=0.05)
        self.assertEqual(output["summary"], "computer_actor_time_budget")
        self.assertEqual(self.calls, [])

    def test_reported_interrupted_usage_is_metered_before_context_release(self):
        self.run_actor("wait", timeout_seconds=0.05)
        self.assertTrue(self.usage)
        self.assertEqual(self.usage[-1]["total_tokens"], 200)

    def test_cancel_ends_inference_without_waiting_for_model_completion(self):
        result = []
        worker = threading.Thread(target=lambda: result.append(self.run_actor("wait")))
        worker.start()
        for _ in range(100):
            if self.actor.transport.turn_id:
                break
            threading.Event().wait(0.01)
        self.actor.cancel()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0][0]["status"], "blocked")
        self.assertEqual(self.calls, [])

    def fail_native_call(self, index, code, *, omit_verification_image=False, recovery_guidance=""):
        original = self.invoke

        def invoke(tool, arguments, call_id):
            result = original(tool, arguments, call_id)
            if len(self.calls) == index:
                return DeviceUseResult("invocation", call_id, {"success": False, "contentItems": [
                    {"type": "inputText", "text": code + ": native failure" + recovery_guidance}]}, None, None, 1)
            if omit_verification_image and len(self.calls) > index:
                return DeviceUseResult("invocation", call_id, {"success": True}, None, None, 1)
            # Exact-window observations carry the same verified image as observe_app.
            if tool == "mac_peekaboo" and arguments["action"] == "observe":
                return DeviceUseResult("invocation", call_id, result.result, b"fresh-window", None, 1)
            return result

        self.invoke = invoke

    def test_recoverable_read_failures_refresh_windows_and_finish_in_the_same_task(self):
        original = self.invoke
        for code in ("MC-PEEKABOO-25", "MC-PEEKABOO-27"):
            with self.subTest(code=code):
                self.calls.clear()
                self.invoke = original
                self.fail_native_call(1, code)
                output, jpeg = self.run_actor("refresh")
                self.assertEqual(output["status"], "completed")
                self.assertEqual([call[1]["action"] for call in self.calls],
                                 ["observe_app", "list_windows", "observe", "click", "observe_app"])
                self.assertIn(code, output["evidence"])
                self.assertIsNotNone(jpeg)

    def test_uncertain_inputs_get_read_only_verification_without_replay(self):
        original = self.invoke
        for code in ("MC-PEEKABOO-20", "MC-PEEKABOO-21", "MC-PEEKABOO-23"):
            with self.subTest(code=code):
                self.calls.clear()
                self.invoke = original
                self.fail_native_call(2, code)
                output, jpeg = self.run_actor()
                self.assertEqual(output["status"], "completed")
                self.assertEqual([call[1]["action"] for call in self.calls], ["observe_app", "click", "observe_app"])
                self.assertIn(code, output["evidence"])
                self.assertIsNotNone(jpeg)

    def test_denials_and_unknown_failures_stop_without_recovery(self):
        original = self.invoke
        for code in ("MC-PEEKABOO-24", "MC-PEEKABOO-01", "unknown_failure"):
            with self.subTest(code=code):
                self.calls.clear()
                self.invoke = original
                self.fail_native_call(2, code)
                output, _ = self.run_actor()
                self.assertEqual(output["summary"], "computer_actor_native_failure")
                self.assertEqual(len(self.calls), 2)

    def test_recovery_cannot_switch_app_or_engine_or_repeat_uncertain_input_with_new_receipt(self):
        original = self.invoke
        for mode, calls in (("uncertain-replay", 3), ("uncertain-other-app", 2), ("uncertain-other-engine", 2)):
            with self.subTest(mode=mode):
                self.calls.clear()
                self.invoke = original
                self.fail_native_call(2, "MC-PEEKABOO-21")
                output, _ = self.run_actor(mode)
                self.assertEqual(output["summary"], "computer_actor_recovery_action_denied")
                self.assertEqual(len(self.calls), calls)

    def test_observation_without_image_does_not_unlock_input_after_uncertainty(self):
        self.fail_native_call(2, "MC-PEEKABOO-21", omit_verification_image=True)
        output, _ = self.run_actor("uncertain-no-image")
        self.assertEqual(output["status"], "blocked")
        self.assertEqual(len(self.calls), 3)

    def test_expired_window_requires_list_refresh_before_another_observation(self):
        self.fail_native_call(1, "MC-PEEKABOO-25")
        output, _ = self.run_actor("refresh-no-list")
        self.assertEqual(output["summary"], "computer_actor_recovery_action_denied")
        self.assertEqual(len(self.calls), 1)

    def test_operator_cannot_claim_completion_before_uncertain_input_is_verified(self):
        self.fail_native_call(2, "MC-PEEKABOO-21", omit_verification_image=True)
        output, _ = self.run_actor()
        self.assertEqual(output["summary"], "computer_actor_recovery_unverified")
        self.assertEqual(output["status"], "blocked")

    def test_same_click_with_different_observation_options_is_not_dispatched_twice(self):
        original = self.invoke
        for mode in ("uncertain-replay-details", "uncertain-replay-image-size", "uncertain-replay-observation-options"):
            with self.subTest(mode=mode):
                self.calls.clear()
                self.invoke = original
                self.fail_native_call(2, "MC-PEEKABOO-21")
                output, _ = self.run_actor(mode)
                self.assertEqual(output["summary"], "computer_actor_recovery_action_denied")
                self.assertEqual([call[1]["element"] for call in self.calls if call[1]["action"] == "click"], ["B1"])

    def test_partial_input_respects_native_recovery_declaration(self):
        original = self.invoke
        guidance = " Full resta attivo: acquisisci una nuova osservazione e continua dal nuovo stato senza duplicare un effetto già avvenuto."
        for mode, declared, expected in (("full", False, "blocked"), ("full", True, "completed")):
            with self.subTest(mode=mode, declared=declared):
                self.calls.clear()
                self.invoke = original
                self.actor.binding.mode = mode
                self.fail_native_call(2, "MC-PEEKABOO-22", recovery_guidance=guidance if declared else "")
                output, _ = self.run_actor()
                self.assertEqual(output["status"], expected)
                self.assertEqual([call[1]["action"] for call in self.calls],
                                 ["observe_app", "click", "observe_app"] if expected == "completed" else ["observe_app", "click"])

    def test_full_partial_input_verification_does_not_authorize_replay(self):
        self.actor.binding.mode = "full"
        self.fail_native_call(2, "MC-PEEKABOO-22", recovery_guidance=
                              " Full resta attivo: acquisisci una nuova osservazione e continua dal nuovo stato.")
        output, _ = self.run_actor("uncertain-replay-details")
        self.assertEqual(output["summary"], "computer_actor_recovery_action_denied")
        self.assertEqual([call[1]["action"] for call in self.calls], ["observe_app", "click", "observe_app"])
