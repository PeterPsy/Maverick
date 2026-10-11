"""Reviewer reproductions on isolated Memory data, including remote adapters."""

import importlib
import unittest
from unittest.mock import patch

from memory_test_fixture import MemoryTestCase


class MemoryReviewRegressions(MemoryTestCase):
    def test_context_preserves_corrected_body_and_separates_old_source(self):
        initial = self.call('ingest_source', adapter_id='inline_markdown',
            source_key='contract', title='Contract',
            body_markdown='Il contratto annuale costa 1200 euro.', compile_after_ingest=True)
        node_id = initial['node']['id']
        self.call('update_node', node_id=node_id, expected_updated_at=initial['node']['updated_at'],
            body='Il contratto annuale costa 9000 euro.', summary='Il contratto annuale costa 9000 euro.')
        for compiled in (False, True):
            with self.subTest(compiled=compiled):
                if compiled:
                    self.call('compile', node_id=node_id)
                item = self.call('context', query='contratto', limit=1)['items'][0]
                self.assertEqual(item['body_text'], 'Il contratto annuale costa 9000 euro.')
                self.assertIn('9000', item['summary'])
                self.assertIn('1200', str(item['source_chunk_matches']))
                self.assertEqual(item['compiled']['verification'], 'conflict' if compiled else 'unverified')

    def test_signs_operators_and_questions_cannot_be_supporting_citations(self):
        pairs = [
            ('Il saldo è 100 euro.', 'Il saldo è −100 euro.'),
            ('Il saldo è +100 euro.', 'Il saldo è -100 euro.'),
            ('La temperatura è > 20 gradi.', 'La temperatura è < 20 gradi.'),
            ('La temperatura è >= 20 gradi.', 'La temperatura è <= 20 gradi.'),
            ('La temperatura è ≥ 20 gradi.', 'La temperatura è ≤ 20 gradi.'),
            ('Il cliente accetta il rinnovo.', 'Il cliente accetta il rinnovo?'),
        ]
        matcher = importlib.import_module('citation_matching')
        for index, (claim, evidence) in enumerate(pairs):
            with self.subTest(claim=claim, evidence=evidence):
                self.assertEqual(matcher.citation_quote(claim, evidence), '')
                node = self.call('remember', title=f'Assertion {index}', body=claim)['node']
                result = self.call('ingest_source', node_id=node['id'], operation='attach_evidence',
                    adapter_id='inline_markdown', source_key=f'assertion-{index}', title='Evidence',
                    body_markdown=evidence, compile_after_ingest=True)
                self.assertEqual(result['compiled']['citations'], [])
                self.assertNotEqual(result['compiled']['compiled_page']['verification'], 'verified')
        for text in ('Il saldo è −100 euro.', 'La temperatura è > 20 gradi.'):
            self.assertEqual(matcher.citation_quote(text, text), text)
        self.assertEqual(matcher.citation_quote('Il cliente accetta il rinnovo?', 'Il cliente accetta il rinnovo?'), '')

    def test_removed_remote_source_stays_removed_through_maintenance_and_compile(self):
        initial = self.remote(compile_after_ingest=True)
        source_id = initial['sources'][0]['id']
        node_id = initial['node']['id']
        self.call('remove_source', source_id=source_id, node_id=node_id,
            expected_updated_at=initial['node']['updated_at'])
        snapshots = importlib.import_module('sources')
        with patch.object(snapshots, 'source_snapshot', side_effect=AssertionError('removed source fetched')):
            maintenance = self.call('maintenance')
            self.assertTrue(all(run['ok'] for run in maintenance['runs']))
            compiled = self.call('compile', node_id=node_id)
        self.assertEqual(compiled['citations'], [])
        self.assertEqual(self.call('source_query', query='contratto')['results'], [])
        item = self.call('context', query='contratto', limit=1)['items'][0]
        self.assertEqual(item['source_chunk_matches'], [])
        self.assertEqual(item['provenance'], [])
        with self.database.connect(self.root) as db:
            self.assertEqual(db.execute('SELECT status FROM sources WHERE id=?', (source_id,)).fetchone()[0], 'deleted')
            self.assertEqual(db.execute('SELECT status FROM source_documents').fetchone()[0], 'deleted')
        # Reimport is the explicit restoration operation; ordinary compile is not.
        restored = self.remote(compile_after_ingest=False)
        self.assertEqual(restored['sources'][0]['id'], source_id)
        self.assertTrue(self.call('source_query', query='contratto')['results'])
        self.assertEqual(self.call('inspect', node_id=node_id)['node']['compiled_page']['freshness'], 'stale')
        self.assertEqual(len(self.call('jobs_list', status='ready')['jobs']), 1)
        self.call('maintenance')
        self.assertEqual(self.call('inspect', node_id=node_id)['node']['compiled_page']['freshness'], 'fresh')

    def test_v4_supports_are_unverified_until_checked_by_new_semantics(self):
        node = self.call('remember', title='Balance', body='Il saldo è 100 euro.')['node']
        with patch('citation_matching.support_relation', return_value='supports'):
            previous = self.call('ingest_source', node_id=node['id'], operation='attach_evidence',
                adapter_id='inline_markdown', source_key='balance', title='Balance evidence',
                body_markdown='Il saldo è −100 euro.', compile_after_ingest=True)
        self.assertEqual(previous['compiled']['compiled_page']['verification'], 'verified')
        with self.database.transaction(self.root) as db:
            db.execute("UPDATE schema_metadata SET value='4' WHERE key='schema_version'")
        self.database.ensure_schema(self.root)
        inspected = self.call('inspect', node_id=node['id'])['node']
        self.assertEqual(inspected['compiled_page']['freshness'], 'stale')
        self.assertEqual(inspected['compiled_page']['verification'], 'unverified')
        self.assertEqual(inspected['citations'], [])
        self.assertEqual(len(self.call('jobs_list', status='ready')['jobs']), 1)
        self.database.ensure_schema(self.root)
        self.assertEqual(len(self.call('jobs_list', status='ready')['jobs']), 1)
        self.call('maintenance')
        checked = self.call('inspect', node_id=node['id'])['node']
        self.assertEqual(checked['compiled_page']['verification'], 'conflict')
        self.assertEqual(checked['citations'], [])

    def test_scopes_precede_limits_in_every_fts_channel(self):
        for index in range(111):
            target = index == 110
            node = self.call('remember', title=f'Contract {index}', body='Il contratto annuale costa 1200 euro.',
                metadata={'project_id': 'target' if target else 'other', 'person_id': 'alice' if target else 'bob'})['node']
            self.call('ingest_source', node_id=node['id'], operation='attach_evidence',
                adapter_id='inline_markdown', source_key=f'contract-{index}', title='Contract evidence',
                body_markdown='Il contratto annuale costa 1200 euro.', compile_after_ingest=True)
        candidates = importlib.import_module('search_candidates')
        for scope in ({'project_id': 'target'}, {'person_id': 'alice'}, {'project_id': 'target', 'person_id': 'alice'}):
            with self.subTest(scope=scope):
                with self.database.connect(self.root) as db:
                    found = candidates.ranked_candidates(db, 'contratto', limit=1, scope=scope)
                self.assertEqual([candidate['id'] for candidate in found], [node['id']])
                self.assertEqual(set(found[0]['match_sources']), {'node', 'wiki_page', 'claim', 'source_chunk'})
                for query in ('contratto', ''):
                    items = self.call('context', query=query, scope=scope, limit=1)['items']
                    self.assertEqual([item['id'] for item in items], [node['id']])

    def test_identical_remote_reimport_preserves_revision_freshness_and_cache(self):
        initial = self.remote(compile_after_ingest=True)
        node_id = initial['node']['id']
        with self.database.connect(self.root) as db:
            ref = dict(db.execute('SELECT * FROM external_refs').fetchone())
            version = dict(db.execute('SELECT * FROM source_versions').fetchone())
        repeated = self.remote(compile_after_ingest=False)
        with self.database.connect(self.root) as db:
            self.assertEqual(dict(db.execute('SELECT * FROM external_refs').fetchone()), ref)
            observed = dict(db.execute('SELECT * FROM source_versions').fetchone())
            self.assertGreater(observed.pop('observed_at'), version.pop('observed_at'))
            self.assertEqual(observed, version)
        self.assertEqual(repeated['node']['updated_at'], initial['node']['updated_at'])
        self.assertEqual(repeated['node']['compiled_page']['freshness'], 'fresh')
        self.assertEqual(self.call('jobs_list', status='ready')['jobs'], [])
        for _ in range(2):
            compiled = self.call('compile', node_id=node_id)
            self.assertTrue(compiled.get('reused'))
            self.assertEqual(compiled['compile_run']['id'], initial['compiled']['compile_run']['id'])

    def test_excluded_node_deletion_keeps_revision_guard(self):
        node = self.call('remember', title='Preference', body='Prefer short replies.')['node']
        excluded = self.call('exclude_node', node_id=node['id'], expected_updated_at=node['updated_at'])['node']
        errors = importlib.import_module('errors')
        with self.assertRaisesRegex(errors.MemoryValidationError, 'changed since'):
            self.call('delete_node', node_id=node['id'], expected_updated_at=node['updated_at'])
        self.assertEqual(self.call('inspect', node_id=node['id'])['node']['status'], 'excluded')
        self.assertTrue(self.call('delete_node', node_id=node['id'], expected_updated_at=excluded['updated_at'], reason='user_removed')['deleted'])
        self.assertEqual(self.call('inspect', node_id=node['id'])['node']['status'], 'deleted')

    def test_remote_reference_change_enqueues_without_changing_curated_fact(self):
        node = self.call('remember', title='Decision', body='Keep the current decision.')['node']
        initial = self.remote(node_id=node['id'], operation='attach_evidence', compile_after_ingest=True)
        changed = self.remote(node_id=node['id'], operation='attach_evidence', title='Revised source title')
        self.assertEqual(changed['node']['body_text'], node['body_text'])
        self.assertEqual(changed['sources'][0]['source_version_id'], initial['sources'][0]['source_version_id'])
        self.assertNotEqual(changed['external_ref']['updated_at'], initial['external_ref']['updated_at'])
        self.assertEqual(changed['node']['compiled_page']['freshness'], 'stale')
        self.assertEqual(len(self.call('jobs_list', status='ready')['jobs']), 1)
        self.call('maintenance')
        self.assertEqual(self.call('inspect', node_id=node['id'])['node']['compiled_page']['freshness'], 'fresh')


if __name__ == '__main__':
    unittest.main()
