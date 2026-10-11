"""Image-label clicks remain bound to the captured window and verified region."""

import json
import unittest

from core.device_use.computer_actor_contract import validate_actor_task
from core.device_use.computer_observation import native_observation
from core.device_use.computer_task_progress import ComputerTaskProgress
from core.device_use.errors import DeviceUseUnavailableError
from core.device_use.models import DeviceUseResult


BUNDLE = 'com.example.pixel'
BUTTONS = {'x': 0, 'y': 0.4, 'width': 1, 'height': 0.6}
DISPLAY = {'x': 0.6, 'y': 0.05, 'width': 0.4, 'height': 0.25}
STEP = {'tool': 'mac_peekaboo', 'target': BUNDLE, 'window_id': 42, 'action': 'click',
        'control': {'label': '7', 'region': BUTTONS},
        'expect': {'label': '7', 'role': 'image_text', 'region': DISPLAY}}


def pixel_observation(generation=1, value='0', *, window=42, records=None, image=True):
    records = records if records is not None else [
        {'label': '7', 'confidence': 0.99, 'bounds': {'x': 0.1, 'y': 0.5, 'width': 0.1, 'height': 0.1}},
        {'label': value, 'confidence': 0.99, 'bounds': {'x': 0.8, 'y': 0.1, 'width': 0.1, 'height': 0.1}}]
    text = (f'observation_mode=pixels_only; snapshot=px1_{generation}; bundle_id={BUNDLE}; window_id={window}\n'
            'pixel_text_source=same_capture; pixel_text_recognition_succeeded=true\n'
            + '\n'.join('pixel_text=' + json.dumps(record) for record in records))
    return DeviceUseResult('fixture', 'call', {'success': True, 'contentItems': [
        {'type': 'inputText', 'text': text}]}, b'jpeg' if image else None, None, 1)


class ComputerPixelProgressTests(unittest.TestCase):
    def setUp(self):
        self.progress = ComputerTaskProgress(validate_actor_task({
            'objective': 'Press seven in exact window', 'completion_criterion': 'Display seven',
            'steps': [STEP], 'completion_check': STEP['expect']}))

    def read(self, result):
        self.progress.record('mac_peekaboo', {'action': 'observe', 'bundle_id': BUNDLE, 'window_id': 42}, result)

    def test_only_locally_recognized_label_center_becomes_a_window_click(self):
        self.read(pixel_observation())
        tool, args = self.progress.prepare({'step_index': 0})
        self.assertEqual(tool, 'mac_peekaboo')
        self.assertEqual(args['action'], 'click_point')
        self.assertEqual(args['snapshot'], 'px1_1')
        self.assertAlmostEqual(args['point_x'], 0.15)
        self.assertAlmostEqual(args['point_y'], 0.55)
        self.assertNotIn('element', args)
        self.assertTrue(args['observe_after'])

    def test_button_text_cannot_verify_the_display(self):
        self.read(pixel_observation())
        self.progress.prepare({'step_index': 0})
        self.read(pixel_observation(2))
        self.assertEqual(self.progress.index, 0)
        self.assertFalse(self.progress.complete())
        self.read(pixel_observation(3, '7'))
        self.assertEqual(self.progress.index, 1)
        self.assertTrue(self.progress.complete())

    def test_unscoped_expected_text_cannot_verify_any_pixel_effect(self):
        observed = native_observation(pixel_observation(value='7'), 'mac_peekaboo', {})
        self.assertFalse(observed.verifies({'text': '7'}))
        self.assertFalse(observed.verifies({'label': '7'}))
        self.assertTrue(observed.verifies(STEP['expect']))

    def test_old_pixel_image_remains_a_valid_observation_without_invented_targets(self):
        self.read(pixel_observation(records=[]))
        self.assertTrue(self.progress.observation.pixels_only)
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'target_missing'):
            self.progress.prepare({'step_index': 0})
        self.assertIsNone(self.progress.pending)

    def test_wrong_window_never_dispatches_or_verifies_a_pinned_step(self):
        self.read(pixel_observation(window=43))
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'exact_window_required'):
            self.progress.prepare({'step_index': 0})
        self.read(pixel_observation())
        self.progress.prepare({'step_index': 0})
        self.read(pixel_observation(2, '7', window=43))
        self.assertIsNotNone(self.progress.pending)
        self.assertEqual(self.progress.index, 0)
        self.assertFalse(self.progress.permits('mac_peekaboo', {'action': 'observe_app', 'bundle_id': BUNDLE}))
        self.assertTrue(self.progress.permits('mac_peekaboo', {'action': 'observe', 'bundle_id': BUNDLE, 'window_id': 42}))

    def test_only_image_bearing_receipt_can_authorize_a_label(self):
        self.read(pixel_observation(image=False))
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'fresh_observation_required'):
            self.progress.prepare({'step_index': 0})

    def test_missing_regions_and_text_input_are_rejected_before_dispatch(self):
        for changed, reason in [({**STEP, 'control': {'label': '7'}}, 'pixel_region_required'),
                                ({**STEP, 'expect': {'text': '7'}}, 'pixel_region_required'),
                                ({**STEP, 'action': 'replace', 'text': 'prepared'}, 'pixel_text_click_only')]:
            with self.subTest(reason=reason):
                progress = ComputerTaskProgress({'steps': [changed]})
                progress.record('mac_peekaboo', {'action': 'observe', 'bundle_id': BUNDLE}, pixel_observation())
                with self.assertRaisesRegex(DeviceUseUnavailableError, reason):
                    progress.prepare({'step_index': 0})
                self.assertIsNone(progress.pending)

    def test_low_confidence_and_invalid_geometry_are_not_click_targets(self):
        base = {'label': '7', 'confidence': 0.99, 'bounds': {'x': 0.1, 'y': 0.5, 'width': 0.1, 'height': 0.1}}
        for record in [{**base, 'confidence': 0.84}, {**base, 'confidence': True},
                       {**base, 'bounds': {**base['bounds'], 'x': -0.1}},
                       {**base, 'bounds': {**base['bounds'], 'width': float('nan')}},
                       {**base, 'bounds': {**base['bounds'], 'y': 0.95}}, []]:
            with self.subTest(record=record):
                observed = native_observation(pixel_observation(records=[record]), 'mac_peekaboo', {})
                self.assertEqual(observed.controls, [])

    def test_duplicate_labels_inside_the_region_are_ambiguous(self):
        record = {'label': '7', 'confidence': 0.99, 'bounds': {'x': 0.1, 'y': 0.5, 'width': 0.1, 'height': 0.1}}
        self.read(pixel_observation(records=[record, record]))
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'target_ambiguous'):
            self.progress.prepare({'step_index': 0})

    def test_failed_or_unattributed_recognition_cannot_supply_actionable_labels(self):
        result = pixel_observation()
        text = result.result['contentItems'][0]['text']
        for metadata in [text.replace('pixel_text_recognition_succeeded=true', 'pixel_text_recognition_succeeded=false'),
                         text.replace('pixel_text_source=same_capture', 'pixel_text_source=unknown')]:
            with self.subTest(metadata=metadata):
                result.result['contentItems'][0]['text'] = metadata
                observed = native_observation(result, 'mac_peekaboo', {})
                self.assertEqual(observed.controls, [])

    def test_region_and_window_schema_rejects_ambiguous_values(self):
        for change in [{'window_id': True}, {'window_id': 0}, {'tool': 'mac_browser'},
                       {'control': {'label': '7', 'region': {**BUTTONS, 'width': 2}}},
                       {'control': {'label': '7', 'region': {**BUTTONS, 'x': True}}}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_actor_task({'objective': 'x', 'completion_criterion': 'y', 'steps': [{**STEP, **change}]})
