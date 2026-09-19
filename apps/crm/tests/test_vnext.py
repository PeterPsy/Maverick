"""Native extension and migration safety regression tests."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from service import handle_action
from store import connect, initialize
from errors import ValidationError
from domains.import_engine import target_fingerprint
from entity_catalog import EXTENSIONS


class CrmVNextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        initialize(self.root)

    def call(self, action, **payload):
        return handle_action(self.root, 'crm.' + action, payload)[1]

    def extension(self, entity, **fields):
        return self.call('create_extension_record', entity_type=entity, **fields)['record']

    def test_schema6_backup_and_additive_migration(self):
        account = self.call('create_account', name='Existing', id='account_original')['account']
        self.call('link_external_ref', crm_entity_type='account', crm_entity_id=account['id'], source_app_id='mail', source_entity_type='email_thread', source_entity_id='existing')
        with connect(self.root) as db:
            before = [tuple(r) for r in db.execute('SELECT * FROM accounts')]
            refs = [tuple(r) for r in db.execute('SELECT * FROM external_refs')]
            db.execute('ALTER TABLE deals DROP COLUMN margin_minor')
            for table in ['import_rows', 'import_jobs', 'import_identities', 'record_links', *(spec['table'] for spec in EXTENSIONS.values())]:
                db.execute(f'DROP TABLE {table}')
            db.execute("UPDATE schema_metadata SET value='6' WHERE key='schema_version'")
        initialize(self.root)
        initialize(self.root)
        with connect(self.root) as db:
            self.assertEqual(before, [tuple(r) for r in db.execute('SELECT * FROM accounts')])
            self.assertEqual(refs, [tuple(r) for r in db.execute('SELECT * FROM external_refs')])
            self.assertIn('margin_minor', [r['name'] for r in db.execute('PRAGMA table_info(deals)')])
        backups = list(Path(self.root).glob('backups/*.sqlite'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()[0], '6')

    def test_future_schema_refused(self):
        with connect(self.root) as db:
            db.execute("UPDATE schema_metadata SET value='999' WHERE key='schema_version'")
        with self.assertRaises(ValidationError):
            initialize(self.root)

    def test_extension_search_reference_link_and_roundtrip(self):
        contact = self.call('create_contact', display_name='Ada')['contact']
        thread = self.extension('conversation_thread', title='Annual review')
        args = dict(source_type='conversation_thread', source_id=thread['id'], target_type='contact', target_id=contact['id'], relationship='participant')
        self.assertEqual(self.call('link_records', **args), self.call('link_records', **args))
        context = self.call('record_context', entity_type='conversation_thread', id=thread['id'])
        self.assertEqual(context['links'][0]['record']['id'], contact['id'])
        self.assertTrue(self.call('search', query='Annual')['results'])
        resolved = handle_action(self.root, 'crm_reference_resolve', {'entity_type': 'conversation_thread', 'entity_id': thread['id']})[1]
        self.assertIn('conversation_threads/', resolved['app_page'])
        export = self.call('export')['export']
        with tempfile.TemporaryDirectory() as target:
            handle_action(target, 'crm.import_commit', {'export': export})
            restored = handle_action(target, 'crm.record_context', {'entity_type': 'conversation_thread', 'id': thread['id']})[1]
            self.assertEqual(restored['links'][0]['record']['id'], contact['id'])

    def test_campaign_integrity_and_no_delivery(self):
        campaign = self.extension('campaign', title='Launch')
        other = self.extension('campaign', title='Other')
        variant = self.extension('campaign_variant', title='A', campaign_id=other['id'])
        with self.assertRaises(ValidationError):
            self.extension('campaign_step', title='First', campaign_id=campaign['id'], variant_id=variant['id'])
        with self.assertRaises(ValidationError):
            self.call('update_extension_record', entity_type='campaign', id=campaign['id'], status='sending')

    def test_typed_custom_objects(self):
        definition = self.extension('custom_object_definition', title='Assets', object_key='asset', fields={'capacity': 'integer'})
        self.extension('custom_object_record', title='Resource', definition_id=definition['id'], fields={'capacity': 5})
        with self.assertRaises(ValidationError):
            self.extension('custom_object_record', title='Bad', definition_id=definition['id'], fields={'capacity': 'bad'})
        with self.assertRaises(ValidationError):
            self.call('update_extension_record', entity_type='custom_object_definition', id=definition['id'], fields={'capacity': 'boolean'})

    def test_archive_hierarchy_and_unarchive_validation(self):
        campaign = self.extension('campaign', title='Launch')
        variant = self.extension('campaign_variant', title='A', campaign_id=campaign['id'])
        with self.assertRaises(ValidationError):
            self.call('archive_record', entity_type='campaign', id=campaign['id'])
        self.call('archive_record', entity_type='campaign_variant', id=variant['id'])
        self.call('archive_record', entity_type='campaign', id=campaign['id'])
        with self.assertRaises(ValidationError):
            self.call('unarchive_record', entity_type='campaign_variant', id=variant['id'])
        self.call('unarchive_record', entity_type='campaign', id=campaign['id'])
        self.call('unarchive_record', entity_type='campaign_variant', id=variant['id'])
        self.assertTrue(self.call('health')['ok'])

    def test_relationship_search_treats_punctuation_as_text(self):
        self.call('create_contact', display_name='Ada', email='ada@example.test')
        self.assertTrue(self.call('search', query='ada@example.test')['results'])
        self.assertEqual(self.call('search', query='"* : -')['results'], [])

    def test_import_plan_pure_atomic_idempotent_and_stale(self):
        source = {'format': 'csv', 'source_id': 'customers', 'entity_type': 'contact', 'csv': 'id,display_name,email\n1,Ada,ada@example.com'}
        with connect(self.root) as db:
            before = target_fingerprint(db)
        plan = self.call('import_plan', source=source)
        self.assertTrue(plan['ok'], plan)
        with connect(self.root) as db:
            self.assertEqual(before, target_fingerprint(db))
        applied = self.call('import_apply', source=source, plan_token=plan['plan_token'])
        self.assertTrue(applied['committed'])
        replay = self.call('import_apply', source=source, plan_token=plan['plan_token'])
        self.assertTrue(replay['replayed'])
        plan = self.call('import_plan', source=source)
        self.assertEqual(plan['skipped_count'], 1)
        self.call('create_account', name='Concurrent change')
        with self.assertRaises(ValidationError):
            self.call('import_apply', source=source, plan_token=plan['plan_token'])

    def test_invalid_batch_leaves_no_partial_data_or_jobs(self):
        source = {'source_id': 'bad', 'entity_type': 'contact', 'rows': [{'display_name': 'Valid'}, {'display_name': 'Invalid', 'account_id': 'missing'}]}
        plan = self.call('import_plan', source=source)
        self.assertFalse(plan['ok'])
        result = self.call('import_apply', source=source, plan_token=plan['plan_token'])
        self.assertFalse(result['committed'])
        with connect(self.root) as db:
            for table in ('contacts', 'import_jobs', 'import_identities'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)

    def test_external_adapter_cents_relationships_and_exclusions(self):
        source = {'format': 'versy', 'source_id': 'external', 'tables': {
            'contacts': [{'id': 'c1', 'full_name': 'Ada', 'owner_id': 'source-owner'}],
            'conversation_threads': [{'id': 't1', 'subject': 'Review', 'participant_ids': '["c1"]'}],
            'expenses': [{'id': 'e1', 'title': 'Train', 'amount_cents': 1299}],
            'integration_settings': [{'api_key_encrypted': 'do-not-copy'}],
            'outreach_campaigns': [{'id': 'm1', 'name': 'Campaign', 'status': 'Attiva'}],
        }}
        plan = self.call('import_plan', source=source)
        self.assertTrue(plan['ok'], plan)
        self.assertNotIn('do-not-copy', json.dumps(plan))
        result = self.call('import_apply', source=source, plan_token=plan['plan_token'])
        self.assertTrue(result['committed'])
        with connect(self.root) as db:
            self.assertEqual(db.execute('SELECT amount_minor FROM expenses').fetchone()[0], 1299)
            self.assertEqual(db.execute('SELECT owner_id FROM contacts').fetchone()[0], '')
            self.assertEqual(db.execute('SELECT status FROM campaigns').fetchone()[0], 'draft')
            self.assertEqual(db.execute('SELECT count(*) FROM record_links').fetchone()[0], 1)
