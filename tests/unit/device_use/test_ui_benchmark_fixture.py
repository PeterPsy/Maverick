"""The benchmark judges actual effects, including async persistence and replay."""

import unittest

from tests.support.ui_benchmark_fixture import BUNDLE, UIBenchmarkFixture


class UIBenchmarkFixtureTests(unittest.TestCase):
    def fixture(self, scenario):
        fixture = UIBenchmarkFixture(scenario, '', render=False)
        self.addCleanup(fixture.close)
        return fixture

    def read(self, fixture):
        return fixture.invoke('mac_peekaboo', {'action': 'observe_app', 'bundle_id': BUNDLE}, 'read')

    def input(self, fixture, label, action='click', text=None):
        element = next(key for key, value in fixture.elements.items() if value['label'] == label)
        arguments = {'bundle_id': BUNDLE, 'action': action, 'element': element, 'snapshot': fixture.receipt}
        if text is not None:
            arguments['text'] = text
        return fixture.invoke('mac_peekaboo', arguments, 'input')

    def test_save_requires_settling_and_close_reopen_persistence(self):
        fixture = self.fixture('async-save')
        self.read(fixture)
        self.input(fixture, 'Title', 'replace', 'PC use benchmark')
        self.assertEqual(fixture.fields['Title'], '')
        self.read(fixture)
        self.input(fixture, 'Save')
        self.read(fixture)
        self.assertEqual(fixture.status, 'Saving')
        self.assertFalse(fixture.valid())
        self.read(fixture)
        self.assertEqual(fixture.status, 'Saved')
        self.assertFalse(fixture.valid())
        self.input(fixture, 'Close'); self.read(fixture)
        self.input(fixture, 'Reopen'); self.read(fixture)
        self.assertTrue(fixture.valid())

    def test_old_target_and_pending_input_are_rejected_without_replay(self):
        fixture = self.fixture('menu')
        self.read(fixture)
        self.assertEqual(fixture.trace[-1]['arguments'], {'action': 'observe_app', 'bundle_id': BUNDLE})
        old_element, old_receipt = next(iter(fixture.elements)), fixture.receipt
        self.read(fixture)
        result = fixture.invoke('mac_peekaboo', {'action': 'click', 'bundle_id': BUNDLE,
            'element': old_element, 'snapshot': old_receipt}, 'stale')
        self.assertFalse(result.result['success'])
        self.assertEqual(fixture.trace[-1]['arguments']['snapshot'], old_receipt)
        self.assertIsNone(fixture.pending)
        self.read(fixture)
        self.input(fixture, 'Theme')
        result = self.input(fixture, 'Theme')
        self.assertFalse(result.result['success'])
        self.read(fixture)
        self.assertTrue(fixture.menu_open)

    def test_calculator_needs_both_correct_results_not_just_final_display(self):
        fixture = self.fixture('calculator')
        fixture.value = '378'
        fixture.results = [(27, 14, '378')]
        self.assertFalse(fixture.valid())
        fixture.results.insert(0, (17, 23, '391'))
        self.assertTrue(fixture.valid())
