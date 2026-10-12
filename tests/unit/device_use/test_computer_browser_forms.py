"""Browser form input must target fresh focus and verify complete values."""

import json
import unittest

from jsonschema import Draft202012Validator

from core.device_use.computer_actor_contract import validate_actor_task
from core.device_use.computer_task_progress import ComputerTaskProgress, STEP_SCHEMA
from core.device_use.errors import DeviceUseUnavailableError
from core.device_use.models import DeviceUseResult


def browser_result(*, value='before', focused=True, editable=True, complete=True,
                   generation=1, image=True, extra=None):
    field = {'kind': 'input', 'identifier': 'subject', 'label': 'Subject',
             'value': value, 'value_complete': complete, 'disabled': False,
             'editable': editable, 'focused': focused, 'focus_signature': 'subject-focus',
             'x': 0.25, 'y': 0.3}
    data = {'tab_id': 'tab-a', 'observation_id': f'read-{generation}',
            'text_focus': {'editable': True, 'signature': 'subject-focus'},
            'page': {'controls': [field, *(extra or [])], 'text': 'Form',
                     'text_complete': True}}
    return DeviceUseResult('fixture', 'call', {'success': True, 'contentItems': [
        {'type': 'inputText', 'text': json.dumps(data)}]}, b'jpeg' if image else None, None, 1)


def browser_task(action='replace', text='new subject'):
    return validate_actor_task({'objective': 'Prepare the subject field',
        'completion_criterion': 'The Subject field contains the supplied text',
        'prepared_text': [text], 'steps': [{'tool': 'mac_browser', 'target': 'tab-a',
            'action': action, 'control': {'identifier': 'subject'}, 'text': text,
            'expect': {'identifier': 'subject', 'value': text}}]})


class ComputerBrowserFormTests(unittest.TestCase):
    def observe(self, progress, result):
        progress.record('mac_browser', {'action': 'observe', 'tab_id': 'tab-a'}, result)

    def test_prepared_text_routes_to_the_existing_native_browser_actions(self):
        for action, native in [('type', 'type_text'), ('replace', 'replace_text')]:
            with self.subTest(action=action):
                progress = ComputerTaskProgress(browser_task(action))
                self.observe(progress, browser_result())
                tool, args = progress.prepare({'step_index': 0})
                self.assertEqual(tool, 'mac_browser')
                self.assertEqual(args, {'action': native, 'tab_id': 'tab-a',
                    'observation_id': 'read-1', 'text': 'new subject', 'observe_after': True})

    def test_wrong_focus_readonly_and_missing_focus_metadata_send_no_input(self):
        for options in [{'focused': False}, {'focused': None}, {'editable': False}]:
            with self.subTest(options=options):
                progress = ComputerTaskProgress(browser_task())
                self.observe(progress, browser_result(**options))
                with self.assertRaisesRegex(DeviceUseUnavailableError, 'browser_focus_required'):
                    progress.prepare({'step_index': 0})
                self.assertIsNone(progress.pending)
                self.assertTrue(progress.observation.fresh)

    def test_focus_on_another_identified_field_never_authorizes_subject_input(self):
        progress = ComputerTaskProgress(browser_task())
        self.observe(progress, browser_result(focused=False, extra=[{
            'kind': 'input', 'identifier': 'recipient', 'label': 'To',
            'editable': True, 'focused': True, 'x': 0.2, 'y': 0.2}]))
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'browser_focus_required'):
            progress.prepare({'step_index': 0})

    def test_a_text_reply_without_its_image_cannot_authorize_input(self):
        progress = ComputerTaskProgress(browser_task())
        self.observe(progress, browser_result(image=False))
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'fresh_observation_required'):
            progress.prepare({'step_index': 0})

    def test_focus_changed_between_page_metadata_and_receipt_sends_no_input(self):
        progress = ComputerTaskProgress(browser_task())
        result = browser_result()
        data = json.loads(result.result['contentItems'][0]['text'])
        data['text_focus']['signature'] = 'recipient-focus'
        result.result['contentItems'][0]['text'] = json.dumps(data)
        self.observe(progress, result)
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'browser_focus_required'):
            progress.prepare({'step_index': 0})
        self.assertIsNone(progress.pending)

    def test_click_focus_then_replace_advances_from_observed_state(self):
        prepared = browser_task()
        prepared['steps'].insert(0, {'tool': 'mac_browser', 'target': 'tab-a',
            'action': 'click', 'control': {'identifier': 'subject'},
            'expect': {'identifier': 'subject', 'focused': True}})
        progress = ComputerTaskProgress(validate_actor_task(prepared))
        self.observe(progress, browser_result(focused=False))
        tool, args = progress.prepare({'step_index': 0})
        self.assertEqual(args['action'], 'click')
        progress.record(tool, args, browser_result(generation=2))
        self.assertEqual(progress.index, 1)
        tool, args = progress.prepare({'step_index': 1})
        self.assertEqual(args['action'], 'replace_text')
        progress.record(tool, args, browser_result(value='new subject', generation=3))
        self.assertTrue(progress.complete())

    def test_focus_expectation_requires_positive_attestation_and_an_identity(self):
        from core.device_use.computer_task_progress import EXPECTATION_SCHEMA, validate_selector
        validator = Draft202012Validator(EXPECTATION_SCHEMA)
        for predicate in [{'focused': True}, {'identifier': 'subject', 'focused': False}]:
            self.assertFalse(validator.is_valid(predicate))
            with self.assertRaisesRegex(ValueError, 'selector_invalid'):
                validate_selector(predicate, expected=True)

    def test_pending_input_is_not_replayed_and_advances_only_after_readback(self):
        progress = ComputerTaskProgress(browser_task())
        self.observe(progress, browser_result())
        tool, args = progress.prepare({'step_index': 0})
        progress.record(tool, args, browser_result(generation=2))
        self.assertFalse(progress.complete())
        with self.assertRaisesRegex(DeviceUseUnavailableError, 'effect_pending'):
            progress.prepare({'step_index': 0})
        self.assertFalse(progress.permits(tool, {'action': 'replace_text', 'tab_id': 'tab-a'}))
        self.observe(progress, browser_result(value='new subject', generation=3))
        self.assertTrue(progress.complete())
        self.assertEqual(progress.index, 1)

    def test_truncated_or_unattested_values_cannot_prove_the_expected_text(self):
        for complete in [False, None]:
            with self.subTest(complete=complete):
                progress = ComputerTaskProgress(browser_task())
                self.observe(progress, browser_result())
                progress.prepare({'step_index': 0})
                self.observe(progress, browser_result(value='new subject', complete=complete))
                self.assertFalse(progress.complete())
                self.assertIsNotNone(progress.pending)

    def test_browser_text_limit_matches_the_native_contract_and_plan_schema(self):
        valid = browser_task(text='x' * 2000)['steps'][0]
        self.assertTrue(Draft202012Validator(STEP_SCHEMA).is_valid(valid))
        invalid = {**valid, 'text': 'x' * 2001}
        self.assertFalse(Draft202012Validator(STEP_SCHEMA).is_valid(invalid))
        with self.assertRaisesRegex(ValueError, 'step_invalid'):
            browser_task(text='x' * 2001)

    def test_supplied_text_still_requires_the_parent_task_preparation(self):
        prepared = browser_task()
        prepared['steps'][0]['text'] = 'unrequested content'
        with self.assertRaisesRegex(ValueError, 'step_invalid'):
            validate_actor_task(prepared)


if __name__ == '__main__':
    unittest.main()
