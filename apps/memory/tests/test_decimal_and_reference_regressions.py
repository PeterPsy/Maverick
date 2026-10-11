"""Full-path regressions for numeric support and removed-reference retrieval."""

import importlib
import json
import unittest
from unittest.mock import patch

from memory_test_fixture import MemoryTestCase


class DecimalAndReferenceRegressions(MemoryTestCase):
    def attach_rate(self, rate, source_rate, key):
        node = self.call('remember', title=f'Rate {key}',
            body=f'Il tasso annuale del contratto è {rate}%.')['node']
        return self.call('ingest_source', node_id=node['id'], operation='attach_evidence',
            adapter_id='inline_markdown', source_key=key, title='Rate evidence',
            body_markdown=f'Il tasso annuale del contratto è {source_rate}%.', compile_after_ingest=True)

    def test_leading_decimals_preserve_value_and_sign_through_compilation(self):
        for index, (rate, source_rate) in enumerate([
            ('.5', '-.5'), ('.5', '5'), ('+.5', '-.5'), ('-.5', '.5'),
            ('.5', '.05'), (',5', '-,5'), ('.5', '−.5'),
            ('.5', '-. 5'), ('5', '-. 5'), ('.5', '. 5'),
        ]):
            with self.subTest(rate=rate, source_rate=source_rate):
                result = self.attach_rate(rate, source_rate, f'rate-{index}')
                self.assertEqual(result['compiled']['citations'], [])
                self.assertNotEqual(result['compiled']['compiled_page']['verification'], 'verified')
                self.assertNotEqual(self.call('inspect', node_id=result['node']['id'])['node']['compiled_page']['verification'], 'verified')
        for index, rate in enumerate(['.5', '+.5', '-.5', '−.5', ',5']):
            with self.subTest(supported=rate):
                result = self.attach_rate(rate, rate, f'equal-{index}')
                self.assertEqual(result['compiled']['compiled_page']['verification'], 'verified')
                self.assertIn(rate, result['compiled']['citations'][0]['quote'])
        matcher = importlib.import_module('citation_matching')
        # Numeric identifier spelling is not an interchangeable quantity.
        self.assertEqual(matcher.citation_quote('Il codice del contratto è 05.', 'Il codice del contratto è 5.'), '')

    def test_unrecognized_numeric_formats_stay_unverified_even_when_identical(self):
        for index, rate in enumerate(['.5e0', '5e-1', '1_000', '1.2.3', '-..5', '1⁄2', '1²', '1\u202f000', '5^2', '-. 5', '- - .5', '~.5', '≈.5']):
            with self.subTest(rate=rate):
                result = self.attach_rate(rate, rate, f'unsupported-{index}')
                self.assertEqual(result['compiled']['citations'], [])
                self.assertEqual(result['compiled']['compiled_page']['verification'], 'unverified')

    def test_v5_numeric_verification_is_revoked_and_recompiled_once(self):
        with patch('citation_matching.support_relation', return_value='supports'):
            previous = self.attach_rate('.5', '5', 'legacy-rate')
        self.assertEqual(previous['compiled']['compiled_page']['verification'], 'verified')
        old_run = previous['compiled']['compile_run']['id']
        node_id = previous['node']['id']
        with self.database.transaction(self.root) as db:
            db.execute("UPDATE schema_metadata SET value='5' WHERE key='schema_version'")
        self.database.ensure_schema(self.root)
        self.database.ensure_schema(self.root)
        inspected = self.call('inspect', node_id=node_id)['node']
        self.assertEqual(inspected['compiled_page']['freshness'], 'stale')
        self.assertEqual(inspected['compiled_page']['verification'], 'unverified')
        self.assertEqual(inspected['citations'], [])
        self.assertEqual(self.call('context', query='contratto', limit=1)['items'][0]['compiled']['verification'], 'unverified')
        self.assertEqual(len(self.call('jobs_list', status='ready')['jobs']), 1)
        self.call('maintenance')
        inspected = self.call('inspect', node_id=node_id)['node']
        self.assertEqual(inspected['compiled_page']['freshness'], 'fresh')
        self.assertNotEqual(inspected['compiled_page']['verification'], 'verified')
        self.assertEqual(inspected['citations'], [])
        compiled = self.call('compile', node_id=node_id)
        self.assertNotEqual(compiled['compile_run']['id'], old_run)
        self.assertTrue(compiled['reused'])

    def test_removed_references_are_absent_from_full_search_and_related_context_but_retained_in_audit(self):
        a = self.call('remember', title='Alpha retrieval anchor', body='Anchorterm identifies the current decision.')['node']
        b = self.call('remember', title='Beta knowledge', body='Current beta decision.')['node']
        preview = 'Archived evidence retained solely for review.'
        initial = self.remote(node_id=b['id'], operation='attach_evidence', preview_text=preview, compile_after_ingest=True)
        source_id = initial['sources'][0]['id']
        self.call('remove_source', source_id=source_id, node_id=b['id'], expected_updated_at=b['updated_at'])
        self.call('link', source_node_id=a['id'], target_node_id=b['id'], weight=1, confidence=1)
        for maintained in (False, True):
            with self.subTest(maintained=maintained):
                if maintained:
                    self.call('maintenance')
                full = self.call('search', query='Beta', limit=1)['results'][0]
                items = self.call('context', query='Anchorterm', limit=2)['items']
                related = next(item for item in items if item['id'] == b['id'])
                self.assertEqual(related['match_sources'], ['related_node'])
                for item in (full, related):
                    self.assertEqual(item['provenance'], [])
                    self.assertEqual(item['storage_references'], [])
                    self.assertEqual(item['compiled'].get('storage_references', []), [])
                    self.assertNotIn('ingest_preview_text', json.dumps(item))
                    self.assertNotIn('file_drive_contract', json.dumps(item))
                wiki = self.call('wiki_query', query='Beta')
                self.assertNotIn('file_drive_contract', json.dumps(wiki))
                refs = importlib.import_module('storage_reference_payloads')
                with self.database.connect(self.root) as db:
                    self.assertEqual(refs.storage_references_for_node(db, b['id']), [])
                    self.assertIsNone(refs.storage_reference_for_citation(db, {
                        'external_ref_id': initial['external_ref']['id'], 'source_id': source_id,
                    }))
                    removed = self.database.row_payload(db.execute('SELECT * FROM sources WHERE id=?', (source_id,)).fetchone())
                    self.assertIsNone(refs.storage_reference_payload(removed))
                    self.assertEqual(refs.storage_reference_payload(removed, include_removed=True)['entity_id'], 'file_drive_contract')
                audited = self.call('inspect', node_id=b['id'])['node']
                self.assertEqual(audited['external_refs'][0]['metadata']['ingest_preview_text'], preview)
                self.assertEqual(audited['storage_references'][0]['entity_id'], 'file_drive_contract')
                self.assertTrue(self.call('inspect_source', source_id=source_id)['versions'])


if __name__ == '__main__':
    unittest.main()
