from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint


class CalendarPwaReadModelTest(unittest.TestCase):
    def test_window_revision_and_exclusions(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            def call(body):
                return run_json_entrypoint(root / 'backend/app_backend.py', cwd=root, payload={
                    'app_id': 'calendar', 'workspace_id': 'default', 'data_root': directory, 'body': body,
                })
            created = call({'action': 'create', 'event': {'title': 'Display', 'startTime': '2026-09-05T10:00:00Z', 'endTime': '2026-09-05T11:00:00Z'}})
            self.assertEqual(created['status_code'], 201, created)
            query = {'action': 'pwa.read_model', 'kind': 'window', 'start_after': '2026-09-01T00:00:00Z', 'end_before': '2026-10-01T00:00:00Z'}
            first = call(query)
            self.assertEqual(first['status_code'], 200, first)
            payload = first['json']
            self.assertEqual(len(payload['payload']['events']), 1)
            self.assertEqual(call({**query, 'known_revision': payload['revision']})['json'], {'revision': payload['revision'], 'not_modified': True})
            self.assertEqual(call({**query, 'end_before': '2028-01-01T00:00:00Z'})['status_code'], 400)
            self.assertEqual(call({**query, 'kind': 'oauth'})['status_code'], 400)
            event = created['json']['event']
            updated = call({'action': 'update', 'id': event['id'], 'expected_revision': event['revision'], 'event': {'title': 'Changed'}})
            self.assertEqual(updated['status_code'], 200, updated)
            self.assertNotEqual(call(query)['json']['revision'], payload['revision'])
