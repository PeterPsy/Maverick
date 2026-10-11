"""Deep native views must not lose controls during a planned UI sequence."""

import unittest

from core.device_use.computer_observation import native_observation
from core.device_use.computer_task_progress import ComputerTaskProgress
from core.device_use.errors import DeviceUseUnavailableError
from core.device_use.models import DeviceUseResult


BUNDLE = 'com.example.deep-view'
READ = {'action': 'observe', 'bundle_id': BUNDLE, 'window_id': 42}
STEP = {'tool': 'mac_peekaboo', 'target': BUNDLE, 'window_id': 42,
        'action': 'click', 'control': {'label': 'Decision model'},
        'expect': {'role': 'AXMenuItem', 'label': 'Luna'}}


def capture(receipt='1', *, menu=False, warning=''):
    text = f'snapshot=ps1_{receipt}; bundle_id={BUNDLE}; window_id=42\n'
    text += ('AXMenuItem (1 found):\n  elem_2 - "Luna"\n' if menu else
             'AXPopUpButton (1 found):\n  elem_1 - "Decision model" - value: "Luna"\n')
    text += warning
    return DeviceUseResult('fixture', 'call', {'success': True, 'contentItems': [
        {'type': 'inputText', 'text': text}]}, b'jpeg', None, 1)


class ComputerTaskObservationDetailTests(unittest.TestCase):
    def setUp(self):
        self.progress = ComputerTaskProgress({'steps': [STEP]})

    def test_tree_depth_and_projection_limits_are_incomplete(self):
        for marker in ('Warning: AX tree truncated at depth 8.',
                       'Warning: AX tree truncated at element count 600.',
                       'observation_text_complete=false', 'pixel_text_complete=false'):
            with self.subTest(marker=marker):
                self.progress.record('mac_peekaboo', READ, capture(warning=marker))
                self.assertFalse(self.progress.state()['observation_text_complete'])
                self.assertTrue(self.progress.observation_arguments('mac_peekaboo', READ)['details'])
        observed = native_observation(capture(), 'mac_peekaboo', READ)
        self.assertTrue(observed.text_complete)

    def test_detailed_capture_stays_detailed_for_reads_and_post_input_capture(self):
        self.progress.record('mac_peekaboo', {**READ, 'details': True}, capture())
        self.assertTrue(self.progress.observation_arguments('mac_peekaboo', READ)['details'])
        self.assertNotIn('details', READ)
        tool, args = self.progress.prepare({'step_index': 0})
        self.assertTrue(args['details'])
        self.assertTrue(args['observe_after'])
        self.progress.record(tool, args, capture('2', menu=True))
        self.assertEqual(self.progress.index, 1)
        self.assertTrue(self.progress.complete())

    def test_detail_escalation_does_not_leak_to_other_windows_apps_or_unplanned_tasks(self):
        self.progress.record('mac_peekaboo', {**READ, 'details': True}, capture())
        for tool, args in [('mac_peekaboo', {**READ, 'window_id': 43}),
                           ('mac_peekaboo', {**READ, 'bundle_id': 'com.example.other'}),
                           ('mac_peekaboo', {'action': 'observe_app', 'bundle_id': BUNDLE}),
                           ('mac_browser', {'action': 'observe', 'tab_id': 'tab'})]:
            with self.subTest(tool=tool, args=args):
                self.assertEqual(self.progress.observation_arguments(tool, args), args)
        unplanned = ComputerTaskProgress({})
        unplanned.record('mac_peekaboo', {**READ, 'details': True}, capture())
        self.assertEqual(unplanned.observation_arguments('mac_peekaboo', READ), READ)

    def test_incomplete_post_input_read_preserves_pending_effect_without_replay(self):
        self.progress.record('mac_peekaboo', READ, capture())
        tool, args = self.progress.prepare({'step_index': 0})
        result = capture('2', warning='Warning: AX tree truncated at depth 8.')
        result.result['contentItems'][0]['text'] = (
            f'snapshot=ps1_2; bundle_id={BUNDLE}; window_id=42\n'
            'Warning: AX tree truncated at depth 8.')
        self.progress.record(tool, args, result)
        self.assertIsNotNone(self.progress.pending)
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'effect_pending'):
            self.progress.prepare({'step_index': 0})
        read = self.progress.observation_arguments('mac_peekaboo', READ)
        self.assertTrue(read['details'])
        self.progress.record('mac_peekaboo', read, capture('3', menu=True))
        self.assertEqual(self.progress.index, 1)
        self.assertTrue(self.progress.complete())
