"""Real provider entrypoints on isolated workspace fixtures, never live accounts."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration_fixture import APP_ROOT, IntegrationFixture


class ProviderContractTests(IntegrationFixture):
    def test_deepgram_preflight_requests_only_declared_key_without_processing_audio(self):
        root = Path(self.root) / 'providers/data/speech'
        root.mkdir(parents=True)
        (root / 'settings.json').write_text('{"transcription_engine":"deepgram"}')
        result = self.provider_backend('speech', {'action': 'transcribe_file', 'workspace_relative_path': 'storage/uploaded/missing.wav'}, surface='secret_selector')
        self.assertEqual(result, {'requires_secrets': True, 'logical_names': ['deepgram-api-key']})
        self.assertEqual([path.name for path in root.iterdir()], ['settings.json'])

    def test_secret_preflight_never_executes_the_business_action(self):
        for app, body in [('mail', {'action': 'mail_create_draft'}), ('calendar', {'action': 'create'}), ('speech', {'action': 'transcribe_file', 'workspace_relative_path': 'storage/uploaded/missing.wav'})]:
            result = self.provider_backend(app, body, surface='secret_selector')
            self.assertEqual(result, {'requires_secrets': False, **({'logical_names': []} if app == 'speech' else {})})
            self.assertEqual(list((Path(self.root) / 'providers/data' / app).iterdir()), [])

    def test_real_mail_draft_is_created_once_without_sending(self):
        root = Path(self.root) / 'providers/data/mail'
        setup = """
import sys
from pathlib import Path
sys.path.insert(0, 'apps/mail/backend')
from database import ensure_schema, connect
root = Path(sys.argv[1]); ensure_schema(root)
with connect(root) as db:
    db.execute("INSERT INTO connections(id, provider, email_address, display_name, status, created_at, updated_at) VALUES ('mailbox', 'gmail', 'sender@example.test', 'Fixture', 'connected', '2030-01-01', '2030-01-01')")
"""
        subprocess.run([sys.executable, '-c', setup, str(root)], cwd=APP_ROOT.parents[1], capture_output=True, text=True, check=True, timeout=20, env={**os.environ, 'PYTHONPATH': str(APP_ROOT.parents[1])})
        op = self.prepared('mail_draft', subject='CRM follow-up', body_text='Reviewed draft only', to='person@example.test', connection_id='mailbox')
        dispatched = self.execute(op)
        body = dispatched['dependency_backend_requests'][0]['body']
        self.assertFalse(self.provider_backend('mail', body, surface='secret_selector')['requires_secrets'])
        self.finish(dispatched, self.provider_backend('mail', body))
        self.assertEqual(self.get(op)['status'], 'succeeded')
        with sqlite3.connect(root / 'mail.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0], 0)

    def test_real_isolated_calendar_and_storage_contracts(self):
        for kind, app, parameters in [('calendar_event', 'calendar', {}), ('document', 'storage', {'content': '# Offer\nReviewed terms'})]:
            op = self.prepared(kind, **parameters)
            dispatched = self.execute(op)
            body = dispatched['dependency_backend_requests'][0]['body']
            if app == 'calendar':
                self.assertFalse(self.provider_backend(app, body, surface='secret_selector')['requires_secrets'])
            result = self.provider_backend(app, body)
            self.finish(dispatched, result)
            current = self.get(op)
            self.assertEqual(current['status'], 'succeeded', current)
            ref = current['result']['external_ref']
            resolve = self.call('integration_link', **self.target, provider_alias=ref['provider_alias'], source_entity_type=ref['source_entity_type'], source_entity_id=ref['source_entity_id'], ref_id=ref['id'])
            resolved = self.provider_backend(app, resolve['dependency_backend_requests'][0]['body'])
            self.finish(resolve, resolved)
            self.assertEqual(self.get(resolve['operation'])['status'], 'succeeded')
        self.assertTrue(self.call('health')['ok'])

    def test_real_checklist_keeps_one_canonical_task(self):
        created = self.provider_backend('checklist', {'action': 'create', 'title': 'CRM followups', 'sections': [{'id': 'section-a', 'title': 'Next steps', 'tasks': []}]})
        checklist_id = created['checklist']['id']
        linked = self.call('integration_link', **self.target, provider_alias='tasks', source_entity_type='checklist', source_entity_id=checklist_id)
        self.finish(linked, self.provider_backend('checklist', linked['dependency_backend_requests'][0]['body']))
        ref = self.get(linked['operation'])['result']['external_ref']
        op = self.prepared('checklist_task', ref_id=ref['id'], section_id='section-a', title='Prepare offer')
        dispatched = self.execute(op)
        self.finish(dispatched, self.provider_backend('checklist', dispatched['dependency_backend_requests'][0]['body']))
        task_ref = self.get(op)['result']['external_ref']
        update = self.prepared('task_status', ref_id=task_ref['id'], status='completed')
        dispatched = self.execute(update)
        self.finish(dispatched, self.provider_backend('checklist', dispatched['dependency_backend_requests'][0]['body']))
        self.assertEqual(self.get(update)['result']['external_ref']['metadata']['status'], 'completed')
        self.assertEqual(self.call('export')['export']['tasks'], [])
        refreshed = self.call('integration_refresh', **self.target)
        for op_id, request in zip(refreshed['operation_ids'], refreshed['dependency_backend_requests']):
            self.finish({'operation': {'id': op_id}, 'dependency_backend_requests': [request]}, self.provider_backend('checklist', request['body']))
        self.assertTrue(self.call('health')['ok'])
