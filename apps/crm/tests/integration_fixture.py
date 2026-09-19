"""Governed provider integration state machine and approval regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / 'backend'))
from service import handle_action


class IntegrationFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.providers = {'mail': 'mail', 'calendar': 'calendar', 'files': 'storage', 'file-write': 'storage', 'tasks': 'checklist', 'speech': 'speech'}
        self.contact = self.call('create_contact', display_name='Person', email='person@example.test')['contact']
        self.target = {'entity_type': 'contact', 'entity_id': self.contact['id']}

    def call(self, action, **payload):
        payload.setdefault('_app_dependencies', {'dependencies': [{'alias': a, 'selected_provider_app_ids': [p]} for a, p in self.providers.items()]})
        return handle_action(self.root, 'crm.' + action, payload)[1]

    def prepared(self, kind='calendar_event', **parameters):
        if kind == 'calendar_event':
            parameters = {'title': 'Review', 'startTime': '2030-10-01T09:00:00Z', 'endTime': '2030-10-01T10:00:00Z', **parameters}
        return self.call('integration_prepare', **self.target, kind=kind, parameters=parameters)['operation']

    def execute(self, op):
        self.call('approve_workflow_proposal', id=op['proposal_id'])
        return self.call('integration_run', id=op['id'])

    def finish(self, dispatched, result, failed=False, provider=None):
        req = dispatched['dependency_backend_requests'][0]
        return self.call('integration_callback', _trusted_surface='dependency_backend_request_callback',
            operation_id=dispatched['operation']['id'], request_id=req['request_id'], dependency_alias=req['dependency_alias'],
            dependency_backend_status='failed' if failed else 'completed',
            dependency_backend_result={'status_code': 200, 'dependency_provider_app_id': provider or self.providers[req['dependency_alias']], 'json': result})

    def get(self, op):
        return self.call('integration_get', id=op['id'])['operation']

    def provider_backend(self, app, body, *, surface='dependency_backend'):
        root = Path(self.root) / 'providers'
        for directory in ('storage/uploaded', 'storage/generated', 'data/' + app):
            (root / directory).mkdir(parents=True, exist_ok=True)
        raw = {'app_id': app, 'workspace_id': 'fixture', 'workspace_root': str(root),
               'data_root': str(root / 'data' / app), 'surface': surface,
               'consumer_app_id': 'crm', 'dependency_alias': 'file-write' if app == 'storage' else app,
               'uploaded_storage_root': str(root / 'storage/uploaded'), 'generated_storage_root': str(root / 'storage/generated'),
               'effective_mode': 'full-access', 'platform_role': 'admin', 'workspace_role': 'owner', 'body': body}
        response = subprocess.run([sys.executable, str(APP_ROOT.parent / app / 'backend/app_backend.py')], input=json.dumps(raw), capture_output=True, text=True, timeout=20, env={**os.environ, 'PYTHONPATH': str(APP_ROOT.parents[1])})
        self.assertEqual(response.returncode, 0, response.stderr)
        result = json.loads(response.stdout)
        if surface == 'secret_selector':
            return result
        self.assertLess(result['status_code'], 400, result)
        return result['json']
