"""Mounted approved read adapters, revisions and exclusion enforcement."""
from pathlib import Path
import tempfile
import unittest

from core.app_sdk.display_models import conditional_display_response, project_display_model
from core.shared.entrypoints import run_json_entrypoint

ROOT = Path(__file__).resolve().parents[3]


class CompletionReadModelsTest(unittest.TestCase):
    def call(self, app, directory, body):
        root = ROOT / 'apps' / app
        return run_json_entrypoint(root / 'backend/app_backend.py', cwd=root, payload={
            'app_id': app, 'workspace_id': 'default', 'data_root': directory, 'body': body,
        })

    def test_mounted_crm_and_mail_conditional_reads(self):
        for app, kinds in [('crm', ['bootstrap', 'schema', 'records_table', 'pipeline_board']), ('mail', ['mailboxes', 'threads']), ('chat', ['projects'])]:
            with self.subTest(app=app), tempfile.TemporaryDirectory() as directory:
                for kind in kinds:
                    first = self.call(app, directory, {'action': 'pwa.read_model', 'kind': kind})
                    self.assertEqual(first['status_code'], 200, first)
                    revision = first['json']['revision']
                    second = self.call(app, directory, {'action': 'pwa.read_model', 'kind': kind, 'known_revision': revision})
                    self.assertEqual(second['json'], {'revision': revision, 'not_modified': True})
                    self.assertNotIn('app_events', second.get('json', {}))
                rejected = self.call(app, directory, {'action': 'pwa.read_model', 'kind': 'send'})
                self.assertEqual(rejected['status_code'], 400, rejected)

    def test_projection_and_revision_are_closed(self):
        shape = {'fields': {'title': 'string'}, 'maps': {'custom_fields': 'scalar'}}
        value = project_display_model({'title': 'Customer', 'authority': 'secret', 'custom_fields': {'token': 'secret', 'region': 'EU'}}, shape)
        self.assertEqual(value, {'title': 'Customer', 'custom_fields': {'region': 'EU'}})
        first = conditional_display_response(value)
        self.assertEqual(conditional_display_response(value, first['revision']), {'revision': first['revision'], 'not_modified': True})
        self.assertNotEqual(conditional_display_response({**value, 'title': 'Changed'})['revision'], first['revision'])
