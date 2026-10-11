"""Regression cases from the Memory reliability audit, on isolated data only."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_memory_app import evict_foreign_backend_modules


class MemoryAuditRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data' / 'memory'
        evict_foreign_backend_modules()
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
        self.addCleanup(sys.path.remove, sys.path[0])
        self.service = importlib.import_module('service')
        self.database = importlib.import_module('database')

    def call(self, action, **values):
        return self.service.handle_action(self.root, {'action': action, **values})[1]

    def note(self, title='Preference', body='Prefer short replies.', **values):
        return self.call('remember', title=title, body=body, **values)['node']

    def ingest(self, text='Il contratto annuale costa 1200 euro.', **values):
        return self.call('ingest_source', adapter_id='inline_markdown', source_key='contract',
                         title='Annual contract', body_markdown=text, compile_after_ingest=True, **values)

    def test_citations_reject_negation_numbers_dates_units_roles_and_uncertainty(self):
        matcher = importlib.import_module('citation_matching')
        pairs = [
            ('Il cliente accetta il rinnovo.', 'Il cliente non accetta il rinnovo.'),
            ('Il contratto annuale costa 1200 euro.', 'Il contratto annuale costa 9000 euro.'),
            ('Alice trasferisce il progetto a Bob.', 'Bob trasferisce il progetto ad Alice.'),
            ('Il progetto scade il 15 ottobre 2026.', 'Il progetto scade il 15 ottobre 2027.'),
            ('Il pacco pesa 12 kg.', 'Il pacco pesa 12 grammi.'),
            ('Il cliente accetta il rinnovo.', 'Forse il cliente accetta il rinnovo.'),
            ('The client accepts the renewal.', 'If the client accepts the renewal, call us.'),
            ('Alice transfers the project to Bob.', 'Bob transfers the project to Alice.'),
        ]
        for claim, source in pairs:
            with self.subTest(claim=claim, source=source):
                self.assertEqual(matcher.citation_quote(claim, source), '')
        self.assertTrue(matcher.citation_quote('Il cliente non accetta il rinnovo.', 'Il cliente non accetta il rinnovo.'))
        self.assertTrue(matcher.citation_quote('Dana owns the renewal evidence.', 'The renewal evidence is owned by Dana.'))
        self.assertEqual(matcher.contradiction_quote('Il contratto annuale costa 1200 euro.', 'Il contratto mensile costa 9000 euro.'), '')

    def test_curated_fact_records_conflict_without_supporting_citation(self):
        node = self.note(body='Il contratto annuale costa 1200 euro.')
        result = self.ingest('Il contratto annuale costa 9000 euro.', node_id=node['id'], operation='attach_evidence')
        self.assertEqual(result['node']['body_text'], node['body_text'])
        self.assertEqual(result['compiled']['citations'], [])
        self.assertEqual(result['compiled']['compiled_page']['verification'], 'conflict')
        self.assertTrue(result['compiled']['claims'][0]['contradictions'])
        self.assertIn('source_conflict', {finding['finding_type'] for finding in result['compiled']['lint_findings']})
        compact = self.call('context', query='contratto')['items'][0]['compiled']
        self.assertEqual(compact['verification'], 'conflict')
        self.assertTrue(all(claim['verification'] == 'conflict' for claim in compact['claims']))

    def test_generated_fact_updates_source_price_and_citations(self):
        initial = self.ingest()
        updated = self.ingest('Il contratto annuale costa 9000 euro.')
        self.assertEqual(initial['node']['id'], updated['node']['id'])
        self.assertNotIn('1200', updated['node']['body_text'])
        self.assertNotIn('1200', updated['node']['summary'])
        self.assertNotEqual(initial['node']['updated_at'], updated['node']['updated_at'])
        self.assertEqual(updated['compiled']['compiled_page']['verification'], 'verified')
        self.assertTrue(all('9000' in citation['quote'] for citation in updated['compiled']['citations']))
        self.assertEqual(self.call('source_query', query='1200')['results'], [])
        self.assertTrue(self.call('source_query', query='1200', include_history=True)['results'])

    def test_shared_source_updates_generated_document_without_copying_target_fact(self):
        generated = self.ingest()
        target = self.note(title='Decision', body='Old decision.')
        updated = self.ingest('Il contratto annuale costa 9000 euro.', node_id=target['id'], operation='replace_fact',
            fact_body='Approve the revised quote.', expected_updated_at=target['updated_at'])
        self.assertEqual(updated['node']['body_text'], 'Approve the revised quote.')
        refreshed = self.call('inspect', node_id=generated['node']['id'])['node']
        self.assertEqual(refreshed['body_text'], 'Il contratto annuale costa 9000 euro.')
        self.assertNotIn('Approve', refreshed['body_text'])

    def test_current_version_can_return_to_deduplicated_A(self):
        a = self.ingest()
        b = self.ingest('Il contratto annuale costa 9000 euro.')
        again = self.ingest()
        self.assertEqual(a['source_version']['id'], again['source_version']['id'])
        self.assertFalse(again['source_version_created'])
        self.assertEqual(again['source']['id'], b['source']['id'])
        inspected = self.call('inspect_source', source_id=a['source']['id'])
        self.assertEqual(inspected['freshness']['latest_source_version_id'], a['source_version']['id'])
        self.assertEqual(sum(v['is_latest'] for v in inspected['versions']), 1)
        self.assertEqual(self.call('source_query', query='1200')['results'][0]['freshness'], 'fresh')
        self.assertEqual(self.call('source_query', query='9000')['results'], [])

    def test_identical_ingest_does_not_stale_or_enqueue_new_work(self):
        first = self.ingest()
        replay = self.call('ingest_source', adapter_id='inline_markdown', source_key='contract', title='Annual contract', body_markdown='Il contratto annuale costa 1200 euro.')
        self.assertEqual(replay['node']['compiled_page']['freshness'], 'fresh')
        self.assertEqual(replay['node']['updated_at'], first['node']['updated_at'])
        self.assertEqual(self.call('jobs_list', status='ready')['jobs'], [])

    def test_fact_operations_are_distinct_guarded_and_keep_revisions(self):
        node = self.note()
        attached = self.ingest('User: Prefer long replies.', node_id=node['id'], operation='attach_evidence')
        self.assertEqual(attached['node']['body_text'], node['body_text'])
        replaced = self.ingest('User: Prefer long replies.', node_id=node['id'], operation='replace_fact', fact_body='Prefer long replies.', expected_updated_at=node['updated_at'])
        self.assertEqual(replaced['node']['body_text'], 'Prefer long replies.')
        self.assertEqual(replaced['node']['metadata']['replaces_revision'], node['updated_at'])
        self.assertTrue(any(rev['snapshot']['body_text'] == node['body_text'] for rev in replaced['node']['revisions']))
        with self.assertRaisesRegex(ValueError, 'reviewed revision'):
            self.ingest('Another preference.', node_id=node['id'], operation='update_fact', expected_updated_at=node['updated_at'])

    def test_graph_search_backend_and_source_only_match(self):
        node = self.note(title='Client record', body='Customer details.')
        self.ingest('The delivery codename is Zaffiro.', node_id=node['id'])
        graph = self.call('graph', query='Zaffiro')
        self.assertEqual([item['id'] for item in graph['nodes']], [node['id']])
        self.assertTrue(graph['nodes'][0]['updated_at'])
        self.assertNotIn('body_text', graph['nodes'][0])

    def test_full_source_match_beats_partial_nodes_before_limit(self):
        self.note(title='Aurora', body='Unrelated note.', importance=1)
        self.note(title='Rinnovo', body='Unrelated note.', importance=1)
        best = self.note(title='Evidence', body='Source reference.', importance=0)
        self.ingest('Aurora rinnovo approvato.', node_id=best['id'])
        result = self.call('search', query='Aurora rinnovo', limit=2)
        self.assertEqual(result['results'][0]['id'], best['id'])
        self.assertIn('approvato', result['results'][0]['source_chunk_matches'][0]['summary'])

    def test_direct_matches_precede_related_and_zero_does_not_expand(self):
        a = self.note(title='Aurora alpha')
        b = self.note(title='Aurora beta')
        noise = self.note(title='Unrelated')
        self.call('link', source_node_id=a['id'], target_node_id=noise['id'], weight=0, confidence=0)
        result = self.call('context', query='Aurora', limit=3)
        self.assertEqual({item['id'] for item in result['items']}, {a['id'], b['id']})
        self.call('link', source_node_id=b['id'], target_node_id=noise['id'], weight=1, confidence=1)
        result = self.call('context', query='Aurora', limit=2)
        self.assertEqual({item['id'] for item in result['items']}, {a['id'], b['id']})

    def test_person_project_scope_applies_before_limit_in_queries_and_browsing(self):
        self.note(metadata={'project_id': 'unrelated', 'person_id': 'Alice'}, importance=1)
        target = self.note(metadata={'project_id': 'target', 'person_id': 'Alice'}, importance=0)
        for query in ('', 'Preference'):
            with self.subTest(query=query):
                scoped = self.call('context', query=query, project_id='target', person_id='Alice', limit=1)
                self.assertEqual([item['id'] for item in scoped['items']], [target['id']])
                graph = self.call('graph', query=query, scope={'project_id': 'target'}, limit=1)
                self.assertEqual([item['id'] for item in graph['nodes']], [target['id']])

    def test_confidence_zero_survives_claims_and_compact_context(self):
        node = self.note(confidence=0)
        compiled = self.call('compile', node_id=node['id'])
        self.assertTrue(all(claim['confidence'] == 0 for claim in compiled['claims']))
        self.assertEqual(self.call('context', query='Preference')['items'][0]['confidence'], 0)

    def test_remember_is_idempotent_per_content_and_scope(self):
        a = self.note(metadata={'project_id': 'one'})
        self.assertEqual(a['id'], self.note(metadata={'project_id': 'one'})['id'])
        b = self.note(metadata={'project_id': 'two'})
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual([x['id'] for x in self.call('context', query='Preference', scope={'project_id': 'one'})['items']], [a['id']])

    def test_removed_node_source_exclusion_and_reimport(self):
        a = self.ingest()
        self.call('delete_node', node_id=a['node']['id'])
        self.assertEqual(self.call('source_query', query='1200')['results'], [])
        self.assertTrue(self.call('source_query', query='1200', include_excluded=True)['results'])
        fresh = self.ingest()
        self.assertNotEqual(a['node']['id'], fresh['node']['id'])
        self.assertEqual(fresh['source_version']['id'], a['source_version']['id'])

    def test_exclusion_is_reversible_and_source_removal_is_separate(self):
        a = self.ingest()
        self.call('exclude_node', node_id=a['node']['id'])
        self.assertEqual(self.call('search', query='1200')['results'], [])
        self.assertEqual(self.call('source_query', query='1200')['results'], [])
        self.call('exclude_node', node_id=a['node']['id'], excluded=False)
        self.assertTrue(self.call('source_query', query='1200')['results'])
        self.call('remove_source', source_id=a['source']['id'])
        self.assertEqual(self.call('source_query', query='1200')['results'], [])
        self.assertTrue(self.call('source_query', query='1200', include_excluded=True)['results'])

    def test_merge_retains_target_fact_and_transfers_evidence(self):
        a = self.ingest()
        target = self.note(title='Curated contract', body='Keep this fact.')
        self.call('merge_nodes', node_id=a['node']['id'], target_node_id=target['id'], expected_updated_at=a['node']['updated_at'], target_updated_at=target['updated_at'])
        result = self.call('inspect', node_id=target['id'])['node']
        self.assertEqual(result['body_text'], 'Keep this fact.')
        self.assertEqual(self.call('inspect', node_id=a['node']['id'])['node']['status'], 'deleted')
        self.assertEqual(self.call('search', query='1200')['results'][0]['id'], target['id'])

    def test_exclusion_can_be_reversed_after_identical_note_is_recreated(self):
        original = self.note()
        self.call('exclude_node', node_id=original['id'])
        duplicate = self.note()
        self.assertNotEqual(original['id'], duplicate['id'])
        restored = self.call('exclude_node', node_id=original['id'], excluded=False)['node']
        self.assertEqual(restored['status'], 'active')
        self.assertIn(duplicate['id'], {item['id'] for item in restored['duplicate_candidates']})

    def test_remote_ingestion_replaces_reviewed_fact_even_with_same_source_version(self):
        node = self.note(body='Il cliente preferisce Roma.')
        source = {'source_kind': 'remote_storage_file', 'owning_app_id': 'storage', 'entity_type': 'file',
            'entity_id': 'file_test', 'file_id': 'file_test', 'metadata': {'provider': 'google_drive',
            'connection_id': 'test-connection', 'drive_file_id': 'test-drive', 'source_version': 'revision-1'}}
        payload = {'node_id': node['id'], 'memory_source': source, 'preview_text': 'Il cliente preferisce Milano.',
            'title': 'Preference', 'compile_after_ingest': True}
        attached = self.call('ingest_source', adapter_id='remote_storage_file', operation='attach_evidence', **payload)
        self.assertEqual(attached['node']['body_text'], node['body_text'])
        self.assertEqual(attached['compiled']['claims'][0]['verification'], 'unverified')
        relevant = attached['compiled']['claims'][0]['related_evidence']
        self.assertEqual(relevant[0]['quote'], 'Il cliente preferisce Milano.')
        self.assertEqual(relevant[0]['evidence_relation'], 'related')
        self.assertIn('storage_reference', relevant[0])
        self.assertIn('source_review_needed', {finding['finding_type'] for finding in attached['compiled']['lint_findings']})
        replaced = self.call('ingest_source', adapter_id='remote_storage_file', operation='replace_fact',
            fact_body='Il cliente preferisce Milano.', expected_updated_at=attached['node']['updated_at'], **payload)
        self.assertEqual(replaced['node']['body_text'], 'Il cliente preferisce Milano.')
        self.assertEqual(replaced['compiled']['compiled_page']['verification'], 'verified')
        self.assertEqual(replaced['node']['confidence'], 0.5)

    def test_no_archive_reads_for_missing_search_and_no_read_writes(self):
        self.ingest(('Evidence for scalability. ' * 400))
        index = importlib.import_module('source_chunk_index')
        with patch.object(index, 'read_body', side_effect=AssertionError('archive read')):
            self.database.ensure_schema(self.root)
            self.assertEqual(self.call('context', query='absentunique')['items'], [])
        with self.database.connect(self.root) as db:
            before = db.execute('SELECT count(*) FROM events').fetchone()[0]
        self.call('search', query='scalability')
        self.call('inspect_source', source_key='inline_markdown:contract')
        with self.database.connect(self.root) as db:
            self.assertEqual(before, db.execute('SELECT count(*) FROM events').fetchone()[0])

    def test_compile_reads_each_chunk_once_and_reuses_unchanged_inputs(self):
        a = self.ingest(' '.join(f'Fact number {index} is documented.' for index in range(30)))
        self.call('update_node', node_id=a['node']['id'], body=' '.join(f'Fact number {index} is documented.' for index in range(20)))
        wiki = importlib.import_module('wiki_citations')
        with self.database.connect(self.root) as db:
            chunks = db.execute('SELECT count(*) FROM source_chunks').fetchone()[0]
        with patch.object(wiki, 'read_body', wraps=wiki.read_body) as reader:
            compiled = self.call('compile', node_id=a['node']['id'])
            self.assertEqual(reader.call_count, chunks)
            again = self.call('compile', node_id=a['node']['id'])
            self.assertTrue(again['reused'])
            self.assertEqual(again['compile_run']['id'], compiled['compile_run']['id'])
            self.assertEqual(reader.call_count, chunks)
        self.assertGreater(len(compiled['claims']), 8)

    def test_final_expired_lease_becomes_terminal(self):
        node = self.note()
        job = self.call('jobs_enqueue', job_type='compile_node', max_attempts=1, payload={'node_id': node['id']})['job']
        self.call('jobs_claim')
        with self.database.transaction(self.root) as db:
            db.execute("UPDATE ingest_jobs SET locked_until='2000-01-01' WHERE id=?", (job['id'],))
        self.assertIsNone(self.call('jobs_claim')['job'])
        self.assertEqual(self.call('jobs_list', status='failed')['jobs'][0]['id'], job['id'])

    def test_source_inspection_has_bounded_version_and_chunk_pages(self):
        for price in (1200, 9000, 5000):
            a = self.ingest(f'Il contratto annuale costa {price} euro.')
        result = self.call('inspect_source', source_id=a['source']['id'], version_limit=1, chunk_limit=1)
        self.assertEqual(len(result['versions']), 1)
        self.assertEqual(len(result['chunks']), 1)
        self.assertEqual(result['pagination']['next_version_offset'], 1)
        self.assertEqual(result['pagination']['total_versions'], 3)

    def test_paginated_history_does_not_hide_stale_current_observation(self):
        a = self.ingest()
        self.ingest('Il contratto annuale costa 9000 euro.')
        self.ingest()
        with self.database.transaction(self.root) as db:
            db.execute("UPDATE source_versions SET metadata_json=? WHERE id=?", (json.dumps({'stale': True, 'stale_reason': 'changed_source'}), a['source_version']['id']))
        result = self.call('inspect_source', source_id=a['source']['id'], version_limit=1)
        self.assertNotEqual(result['versions'][0]['id'], a['source_version']['id'])
        self.assertEqual(result['freshness']['state'], 'stale')
        self.assertEqual(result['freshness']['stale_version_count'], 2)
        self.assertIn('changed_source', result['freshness']['reasons'])

    def test_v3_migration_invalidates_unverified_citations_and_recovers_pointer(self):
        a = self.ingest()
        b = self.ingest('Il contratto annuale costa 9000 euro.')
        self.ingest()
        with self.database.transaction(self.root) as db:
            db.execute("UPDATE schema_metadata SET value='3' WHERE key='schema_version'")
            db.execute("UPDATE sources SET current_version_id=''")
            db.execute("UPDATE citations SET evidence_relation='unverified'")
        self.database.ensure_schema(self.root)
        self.database.ensure_schema(self.root)
        with self.database.connect(self.root) as db:
            self.assertEqual(db.execute('SELECT current_version_id FROM sources WHERE id=?', (a['source']['id'],)).fetchone()[0], a['source_version']['id'])
            self.assertNotEqual(a['source_version']['id'], b['source_version']['id'])
            self.assertEqual(db.execute('SELECT freshness FROM wiki_pages WHERE node_id=?', (a['node']['id'],)).fetchone()[0], 'stale')
            self.assertEqual(db.execute("SELECT count(*) FROM ingest_jobs WHERE dedupe_key=?", ('compile_node:migration:5:' + a['node']['id'],)).fetchone()[0], 1)
        self.call('maintenance')
        self.assertEqual(self.call('inspect', node_id=a['node']['id'])['node']['compiled_page']['verification'], 'verified')

    def test_foreground_maintenance_drains_at_most_three_compiles(self):
        for index in range(5):
            self.call('ingest_source', adapter_id='inline_markdown', source_key=str(index), body_markdown=f'Fact {index}.')
        result = self.call('maintenance')
        self.assertLessEqual(result['jobs_run'], 3)
        self.assertTrue(result['jobs_run'])
        self.assertEqual(len(self.call('jobs_list', status='done')['jobs']), result['jobs_run'])

    def test_node_edit_does_not_report_the_source_outdated(self):
        result = self.ingest()
        self.call('update_node', node_id=result['node']['id'], body='The user added a note.')
        inspected = self.call('inspect', node_id=result['node']['id'])['node']
        self.assertEqual(inspected['compiled_page']['compilation_state'], 'stale')
        self.assertEqual(inspected['compiled_page']['source_state'], 'current')

    def test_compact_projection_never_loads_full_body_pages_or_claims(self):
        result = self.ingest('A verified statement. ' * 300)
        projection = importlib.import_module('retrieval_projections')
        with self.database.connect(self.root) as db:
            queries = []
            db.set_trace_callback(queries.append)
            payload = projection.compact_projections(db, [result['node']['id']], data_root=self.root)
        self.assertLessEqual(len(payload[result['node']['id']]['compiled']['claims']), 3)
        self.assertFalse(any('SELECT * FROM claims' in sql or 'SELECT * FROM wiki_pages' in sql for sql in queries))
        self.assertNotIn('body_markdown', payload[result['node']['id']]['compiled'])

    def test_local_source_change_is_observed_without_persisted_read_writes(self):
        from unittest.mock import patch
        snapshots = importlib.import_module('sources')
        lint = importlib.import_module('lint')
        node = self.note(body='The rate is 1200 euro.')
        self.call('attach_file', node_id=node['id'], workspace_relative_path='storage/generated/rate.md', title='Rates')
        def snapshot(value, data_root=None, **kwargs):
            return {'hash': 'original', 'hash_kind': 'canonical_body', 'extracted_text': 'The rate is 1200 euro.', 'extracted_ref': 'rate', 'metadata': {}}
        with patch.object(snapshots, 'source_snapshot', side_effect=snapshot), patch.object(lint, 'source_snapshot', side_effect=snapshot), patch('wiki_content.source_snapshot', side_effect=snapshot):
            self.call('compile', node_id=node['id'])
        with patch.object(lint, 'source_snapshot', return_value={'hash': 'changed'}):
            inspected = self.call('inspect', node_id=node['id'])['node']
        self.assertEqual(inspected['compiled_page']['freshness'], 'stale')
        with self.database.connect(self.root) as db:
            self.assertEqual(db.execute('SELECT freshness FROM wiki_pages WHERE node_id=?', (node['id'],)).fetchone()[0], 'fresh')
        with patch.object(lint, 'source_snapshot', return_value={'hash': 'changed'}):
            self.call('lint', node_id=node['id'])
        with self.database.connect(self.root) as db:
            self.assertEqual(db.execute('SELECT freshness FROM wiki_pages WHERE node_id=?', (node['id'],)).fetchone()[0], 'stale')

    def test_stale_compiled_claims_do_not_reintroduce_replaced_fact(self):
        result = self.ingest()
        self.call('update_node', node_id=result['node']['id'], body='Il contratto annuale costa 9000 euro.', summary='Il contratto annuale costa 9000 euro.')
        context = self.call('context', query='contratto')['items'][0]
        self.assertNotIn('1200', json.dumps(context['compiled']))
        self.assertEqual(context['compiled']['verification'], 'unverified')
        self.assertEqual(context['compiled']['freshness'], 'stale')


if __name__ == '__main__':
    unittest.main()
