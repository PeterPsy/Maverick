"""Mounted approved read adapters, revisions and exclusion enforcement."""
from pathlib import Path
import sqlite3
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

    def test_populated_crm_record_tags_survive_display_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            created = self.call('crm', directory, {'action': 'crm.create_account', 'name': 'Test customer', 'status': 'prospect'})
            self.assertEqual(created['status_code'], 201, created)
            account = created['json']['account']
            tagged = self.call('crm', directory, {'action': 'crm.tag_record', 'entity_type': 'account', 'id': account['id'], 'tag': 'Reviewed'})
            self.assertEqual(tagged['status_code'], 200, tagged)
            for kind in ('get', 'records_table', 'bootstrap', 'search'):
                result = self.call('crm', directory, {'action':'pwa.read_model', 'kind':kind, 'entity_type':'account', 'id':account['id'], 'query':'Test'})
                self.assertEqual(result['status_code'], 200, result)
                self.assertIn('Test customer' if kind == 'search' else 'Reviewed', str(result['json']), kind)

    def test_consulted_mail_body_is_complete_and_provider_material_cannot_change_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            self.call('mail', directory, {'action':'health.check'})
            with sqlite3.connect(Path(directory) / 'mail.sqlite') as db:
                db.execute("INSERT INTO connections(id,provider,email_address,display_name,status,scopes_json,created_at,updated_at) VALUES ('c','imap_smtp','test@example.invalid','Test','connected','[]','2026-09-05','2026-09-05')")
                db.execute("INSERT INTO threads(id,connection_id,provider_thread_id,subject,participants_json,last_message_at,snippet,unread,starred,labels_json,updated_at) VALUES ('t','c','private-locator','Test','[]','2026-09-05','Snippet',0,0,'[]','2026-09-05')")
                db.execute("INSERT INTO messages(id,thread_id,provider_message_id,sender_json,recipients_json,sent_at,body_text,body_html_sanitized,headers_json,has_attachments) VALUES ('m','t','private-locator','{\"email\":\"sender@example.invalid\"}','[]','2026-09-05','Complete body','<b>Complete body</b>','{\"token\":\"secret\"}',0)")
            for kind, field in [('thread','thread'),('message','message')]:
                query={'action':'pwa.read_model','kind':kind,'thread_id':'t','message_id':'m','max_body_chars':1000}
                first=self.call('mail',directory,query)
                self.assertEqual(first['status_code'],200,first)
                model=first['json']['payload']['data'][field]
                message=model['messages'][0] if kind=='thread' else model
                self.assertEqual(message['body_text'],'Complete body')
                self.assertFalse(message['body_truncated'])
                self.assertNotIn('private-locator',str(first))
                self.assertNotIn('secret',str(first))
                revision=first['json']['revision']
                with sqlite3.connect(Path(directory) / 'mail.sqlite') as db:
                    db.execute("UPDATE messages SET headers_json=? WHERE id='m'", ('{"token":"changed-provider-secret"}',))
                self.assertEqual(self.call('mail',directory,{**query,'known_revision':revision})['json'], {'revision':revision,'not_modified':True})

    def test_projection_and_revision_are_closed(self):
        shape = {'fields': {'title': 'string'}, 'maps': {'custom_fields': 'scalar'}}
        value = project_display_model({'title': 'Customer', 'authority': 'secret', 'custom_fields': {'token': 'secret', 'region': 'EU'}}, shape)
        self.assertEqual(value, {'title': 'Customer', 'custom_fields': {'region': 'EU'}})
        first = conditional_display_response(value)
        self.assertEqual(conditional_display_response(value, first['revision']), {'revision': first['revision'], 'not_modified': True})
        self.assertNotEqual(conditional_display_response({**value, 'title': 'Changed'})['revision'], first['revision'])
