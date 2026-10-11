"""Semantic targets, delayed effects and verified model handoff boundaries."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.device_use.computer_actor_contract import validate_actor_task
from core.device_use.computer_observation import native_observation
from core.device_use.computer_task_execution import execute_computer_task
from core.device_use.computer_task_progress import ComputerTaskProgress
from core.device_use.errors import DeviceUseUnavailableError
from core.device_use.models import DeviceUseResult


BUNDLE = 'com.example.fixture'
STEP = {'tool': 'mac_peekaboo', 'target': BUNDLE, 'action': 'click',
        'control': {'identifier': 'Seven'}, 'expect': {'role': 'statictext', 'value': '7'}}


def observation(generation=1, value='0', *, duplicate=False, success=True, image=True):
    text = (f'snapshot=ps1_{generation}; bundle_id={BUNDLE}; window_id=42\n'
            f'AXButton (2 found):\n  elem_{generation * 10} - "7" - identifier: Seven\n'
            f'AXStaticText (1 found):\n  elem_{generation * 10 + 1} - "\u200e{value}" - value: "\u200e{value}" - [not actionable]\n')
    if duplicate:
        text += f'AXButton (1 found):\n  elem_999 - "7" - identifier: Seven\n'
    return DeviceUseResult('fixture', 'call', {'success': success, 'contentItems': [
        {'type': 'inputText', 'text': text}]}, b'jpeg' if image else None, None, 1)


def task():
    return validate_actor_task({'objective': 'Press seven', 'completion_criterion': 'Display seven', 'steps': [STEP]})


class ComputerTaskProgressTests(unittest.TestCase):
    def setUp(self):
        self.progress = ComputerTaskProgress(task())

    def read(self, result):
        self.progress.record('mac_peekaboo', {'action': 'observe_app', 'bundle_id': BUNDLE}, result)

    def test_resolves_changing_ids_from_the_latest_receipt(self):
        self.read(observation(1))
        self.read(observation(2))
        tool, args = self.progress.prepare({'step_index': 0})
        self.assertEqual((tool, args['element'], args['snapshot']), ('mac_peekaboo', 'elem_20', 'ps1_2'))
        self.assertTrue(args['observe_after'])

    def test_pending_capture_does_not_advance_or_authorize_another_input(self):
        self.read(observation())
        self.progress.prepare({'step_index': 0})
        self.read(observation(2, '0'))
        self.assertEqual(self.progress.index, 0)
        self.assertFalse(self.progress.complete())
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'effect_pending'):
            self.progress.prepare({'step_index': 0})
        self.assertFalse(self.progress.permits('mac_peekaboo', {'action': 'click', 'bundle_id': BUNDLE}))
        self.read(observation(3, '7'))
        self.assertEqual(self.progress.index, 1)
        self.assertTrue(self.progress.complete())

    def test_button_label_is_not_a_display_value(self):
        self.read(observation())
        self.assertFalse(self.progress.observation.verifies({'role': 'statictext', 'value': '7'}))
        self.assertTrue(self.progress.observation.verifies({'identifier': 'Seven'}))

    def test_truncated_completion_read_requests_metadata_without_replaying_input(self):
        self.progress.completion_check = {'role': 'statictext', 'value': '7'}
        self.read(observation())
        self.progress.prepare({'step_index': 0})
        self.read(observation(2, '7'))
        self.assertTrue(self.progress.state()['completion_verified'])
        truncated = observation(3)
        truncated.result['contentItems'][0]['text'] = (
            f'snapshot=ps1_3; bundle_id={BUNDLE}; window_id=42\n'
            'AXButton (1 found):\n  elem_30 - "7" - identifier: Seven\n'
            'observation_text_complete=false')
        self.read(truncated)
        state = self.progress.state()
        self.assertEqual(state['verified_steps'], 1)
        self.assertFalse(state['completion_verified'])
        self.assertFalse(state['observation_text_complete'])
        self.assertFalse(state['effect_pending'])
        self.read(observation(4, '7'))
        self.assertTrue(self.progress.state()['completion_verified'])
        self.assertEqual(self.progress.index, 1)

    def test_visible_text_matches_exact_labels_and_values_not_substrings(self):
        observed = native_observation(observation(value='17'), 'mac_peekaboo', {})
        self.assertTrue(observed.verifies({'text': '17'}))
        self.assertFalse(observed.verifies({'text': '1'}))

    def test_menu_item_appearance_can_verify_an_open_menu(self):
        from tests.support.ui_benchmark_fixture import BUNDLE as fixture_bundle, UIBenchmarkFixture
        fixture = UIBenchmarkFixture('menu', '', render=False)
        self.addCleanup(fixture.close)
        plan = {'steps': [{'tool': 'mac_peekaboo', 'target': fixture_bundle, 'action': 'click',
                          'control': {'label': 'Theme'}, 'expect': {'text': 'Dark'}}]}
        progress = ComputerTaskProgress(plan)
        read = {'action': 'observe_app', 'bundle_id': fixture_bundle}
        progress.record('mac_peekaboo', read, fixture.invoke('mac_peekaboo', read, 'read'))
        tool, args = progress.prepare({'step_index': 0})
        progress.record(tool, args, fixture.invoke(tool, args, 'input'))
        self.assertIsNotNone(progress.pending)
        progress.record('mac_peekaboo', read, fixture.invoke('mac_peekaboo', read, 'settle'))
        self.assertEqual(progress.index, 1)

    def test_duplicates_and_missing_images_fail_before_dispatch(self):
        self.read(observation(duplicate=True))
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'target_ambiguous'):
            self.progress.prepare({'step_index': 0})
        self.read(observation(image=False))
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'fresh_observation_required'):
            self.progress.prepare({'step_index': 0})

    def test_skipped_steps_and_raw_inputs_cannot_bypass_the_plan(self):
        self.read(observation())
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'step_mismatch'):
            self.progress.prepare({'step_index': 1})
        self.assertFalse(self.progress.permits('mac_peekaboo', {'action': 'click'}))

    def test_three_unverified_reads_stop_without_replay(self):
        self.read(observation())
        self.progress.prepare({'step_index': 0})
        self.read(observation(2))
        self.read(observation(3))
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'effect_not_verified'):
            self.read(observation(4))
        self.assertIsNotNone(self.progress.pending)

    def test_only_explicit_pre_dispatch_failure_clears_the_pending_effect(self):
        self.read(observation())
        self.progress.prepare({'step_index': 0})
        for text, pending in [('MC-PEEKABOO-21: uncertain', True),
                              ('MC-INTEGRATION-01: nessuna azione inviata. Full resta attivo', False)]:
            failed = DeviceUseResult('fixture', 'call', {'success': False, 'contentItems': [
                {'type': 'inputText', 'text': text}]}, None, None, 1)
            self.progress.record('mac_peekaboo', {'action': 'click', 'bundle_id': BUNDLE}, failed)
            self.assertEqual(self.progress.pending is not None, pending)

    def test_failed_verification_read_does_not_clear_previously_dispatched_input(self):
        self.read(observation())
        self.progress.prepare({'step_index': 0})
        failed = DeviceUseResult('fixture', 'read', {'success': False, 'contentItems': [
            {'type': 'inputText', 'text': 'MC-INTEGRATION-01: nessuna azione inviata. Full resta attivo'}]}, None, None, 1)
        self.read(failed)
        self.assertIsNotNone(self.progress.pending)
        self.assertFalse(self.progress.complete())
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'effect_pending'):
            self.progress.prepare({'step_index': 0})

    def test_unprepared_text_and_oversized_plans_are_rejected(self):
        base = {'objective': 'x', 'completion_criterion': 'y'}
        for extra in [{'steps': [STEP] * 33}, {'steps': [{**STEP, 'action': 'replace', 'text': 'invented'}]},
                      {'completion_check': {'text': 'Saved', 'value': '1'}}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_actor_task({**base, **extra})


class ComputerTaskExecutionTests(unittest.TestCase):
    def actor(self, model):
        return Mock(model_id=model, reasoning_effort='low')

    def test_unplanned_luna_low_task_does_not_run_inference_or_input(self):
        client = self.actor('gpt-6-luna')
        output, _ = execute_computer_task(client, {'objective': 'navigate'}, binding=SimpleNamespace(initial_app=BUNDLE),
            invoke=Mock(), active=lambda: True, usage_sink=Mock())
        self.assertEqual(output['summary'], 'computer_actor_plan_required')
        self.assertEqual(output['steps'], 0)
        client.run.assert_not_called()

    def test_unplanned_luna_low_routes_to_configured_sol_before_input(self):
        client, fallback = self.actor('gpt-6-luna'), self.actor('gpt-6.1-sol')
        fallback.run.return_value = ({'status': 'completed', 'summary': 'done', 'steps': 2}, b'jpeg')
        output, _ = execute_computer_task(client, {'objective': 'navigate'}, binding=SimpleNamespace(initial_app=BUNDLE),
            invoke=Mock(), active=lambda: True, usage_sink=Mock(), fallback_factory=lambda: fallback)
        client.run.assert_not_called()
        self.assertTrue(output['fallback_used'])
        self.assertEqual(output['attempts'][0]['reason'], 'computer_actor_plan_required')
        self.assertEqual(output['steps'], 2)
        fallback.close.assert_called_once()

    def test_handoff_reuses_verified_progress_and_counts_both_attempts(self):
        first, second = self.actor('luna'), self.actor('sol')
        two_steps = task()
        two_steps['steps'] = [STEP, STEP]
        recovery_seen = []
        def run_first(task, **kwargs):
            progress = kwargs['progress']
            progress.index = 1
            progress.observation = native_observation(observation(2, '7'), 'mac_peekaboo', {})
            recovery_seen.append(kwargs['recovery'])
            return {'status': 'needs_decision', 'summary': 'computer_actor_step_mismatch', 'steps': 3}, b'jpeg'
        def run_second(task, **kwargs):
            self.assertEqual(kwargs['progress'].index, 1)
            self.assertIs(kwargs['recovery'], recovery_seen[0])
            self.assertLessEqual(kwargs['max_steps'], 61)
            self.assertLessEqual(kwargs['timeout_seconds'], 180)
            return {'status': 'completed', 'summary': 'done', 'steps': 2}, b'jpeg'
        first.run.side_effect, second.run.side_effect = run_first, run_second
        output, _ = execute_computer_task(first, two_steps, binding=SimpleNamespace(initial_app=BUNDLE),
            invoke=Mock(), active=lambda: True, usage_sink=Mock(), fallback_factory=lambda: second)
        self.assertTrue(output['fallback_used'])
        self.assertEqual(output['steps'], 5)
        self.assertEqual([item['model_id'] for item in output['attempts']], ['luna', 'sol'])
        second.close.assert_called_once()

    def test_uncertain_or_incomplete_step_cannot_launch_another_model(self):
        client, fallback = self.actor('luna'), Mock()
        def run(task, **kwargs):
            kwargs['progress'].index = 1
            kwargs['progress'].pending = STEP
            return {'status': 'needs_decision', 'summary': 'computer_actor_step_mismatch', 'steps': 2}, None
        client.run.side_effect = run
        execute_computer_task(client, task(), binding=SimpleNamespace(initial_app=BUNDLE),
            invoke=Mock(), active=lambda: True, usage_sink=Mock(), fallback_factory=fallback)
        fallback.assert_not_called()

    def test_plan_can_handoff_at_first_boundary_when_no_input_was_sent(self):
        first, second = self.actor('luna'), self.actor('sol')
        def reject(task, **kwargs):
            kwargs['progress'].observation = native_observation(observation(), 'mac_peekaboo', {})
            return {'status': 'needs_decision', 'summary': 'computer_actor_step_mismatch', 'steps': 1}, b'jpeg'
        first.run.side_effect = reject
        second.run.return_value = ({'status': 'completed', 'summary': 'done', 'steps': 2}, b'jpeg')
        result, _ = execute_computer_task(first, task(), binding=SimpleNamespace(initial_app=BUNDLE),
            invoke=Mock(), active=lambda: True, usage_sink=Mock(), fallback_factory=lambda: second)
        self.assertTrue(result['fallback_used'])

    def test_model_reported_difficulty_can_handoff_only_at_a_safe_boundary(self):
        first, second = self.actor('luna'), self.actor('sol')
        def difficulty(task, **kwargs):
            kwargs['progress'].observation = native_observation(observation(), 'mac_peekaboo', {})
            return {'status': 'blocked', 'summary': 'Could not resolve the current control', 'steps': 1}, b'jpeg'
        first.run.side_effect = difficulty
        second.run.return_value = ({'status': 'completed', 'summary': 'done', 'steps': 2}, b'jpeg')
        result, _ = execute_computer_task(first, task(), binding=SimpleNamespace(initial_app=BUNDLE),
            invoke=Mock(), active=lambda: True, usage_sink=Mock(), fallback_factory=lambda: second)
        self.assertTrue(result['fallback_used'])
