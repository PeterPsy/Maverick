"""Review cases for critical continuation, source integrity and inspector state."""

import importlib
import json
from unittest.mock import patch

from memory_test_fixture import MemoryTestCase


class NavigationReviewRegressions(MemoryTestCase):
    def remember(self, title, body=None):
        return self.call('remember', title=title, body=body or title)['node']

    def attach(self, node_id, key, text, compile_now=True):
        return self.call('ingest_source', node_id=node_id, operation='attach_evidence',
                         adapter_id='inline_markdown', source_key=key, title='Evidence',
                         body_markdown=text, compile_after_ingest=compile_now)

    def chunk_path(self, node_id):
        with self.database.connect(self.root) as db:
            row = db.execute('''SELECT sc.body_path FROM source_chunks sc
                JOIN sources s ON s.current_version_id=sc.source_version_id
                JOIN node_source_links nl ON nl.source_id=s.id WHERE nl.node_id=?''', (node_id,)).fetchone()
        return self.root / row['body_path']

    def matching_chunk_paths(self, query):
        with self.database.connect(self.root) as db:
            return [row['body_path'] for row in db.execute('''SELECT sc.body_path,
                bm25(source_chunk_fts) AS rank FROM source_chunk_fts
                JOIN source_chunks sc ON sc.id=source_chunk_fts.chunk_id
                WHERE source_chunk_fts MATCH ? ORDER BY rank,sc.chunk_index,sc.id''', (query,))]

    def test_critical_continuation_detects_more_edges_of_a_single_kind(self):
        for kind in ('contradicts', 'supersedes'):
            with self.subTest(kind=kind):
                seed = self.remember('Anchor ' + kind)['id']
                for index in range(3):
                    other = self.remember(f'Other {kind} {index}')['id']
                    self.call('link', source_node_id=seed, target_node_id=other, kind=kind)
                result = self.call('context', query=seed, limit=1)
                self.assertEqual(len(result['critical_edges']), 2)
                self.assertTrue(result['critical_has_more'])
                explored = self.call('explore', node_ids=[seed], kinds=[kind])
                self.assertEqual(len(explored['edges']), 3)

    def test_invalid_source_only_hits_are_excluded_without_losing_continuation(self):
        for damage, query in (('hash', 'Zebraquartz'), ('missing', 'Tigerquartz')):
            with self.subTest(damage=damage):
                nodes = [self.remember(f'Unrelated {damage} {index}', 'Prefer short replies.') for index in range(2)]
                for index, node in enumerate(nodes):
                    self.attach(node['id'], f'{damage}-{index}', f'{query} is the unique evidence word {index}.')
                indexed = self.call('search', query=query, limit=2)['results']
                rejected, valid = [item['id'] for item in indexed]
                path = self.chunk_path(rejected)
                if damage == 'hash':
                    path.write_text('Changed contents.', encoding='utf-8')
                else:
                    path.unlink()
                for action, detail in (('context', {}), ('search', {'detail': 'evidence'})):
                    first = self.call(action, query=query, limit=1, **detail)
                    key = 'items' if action == 'context' else 'results'
                    self.assertEqual(first[key], [])
                    cursor = first['search_next_cursor'] if action == 'context' else first['next_cursor']
                    self.assertTrue(first['has_more'])
                    self.assertIsNotNone(cursor)
                    second = self.call(action, query=query, limit=1, cursor=cursor, **detail)
                    self.assertEqual([item['node_id'] for item in second[key]], [valid])
                    self.assertFalse(second['has_more'])

    def test_invalid_source_channel_does_not_hide_a_valid_node_text_match(self):
        node = self.remember('Uniquequartz preference', 'Prefer short replies.')
        self.attach(node['id'], 'channel', 'Uniquequartz is the evidence word.')
        self.chunk_path(node['id']).unlink()
        for action, detail in (('context', {}), ('search', {'detail': 'evidence'})):
            result = self.call(action, query='Uniquequartz', **detail)
            item = result['items' if action == 'context' else 'results'][0]
            self.assertEqual(item['node_id'], node['id'])
            self.assertNotIn('source_chunk', item['match_sources'])
            self.assertEqual(item['source_chunk_matches'], [])
            self.assertNotIn('source passage', item['reason'])

    def test_source_validation_keeps_sparse_hits_beside_a_long_source(self):
        dense = self.remember('Unrelated dense document', 'Prefer short replies.')['id']
        sparse = self.remember('Unrelated sparse document', 'Prefer short replies.')['id']
        self.attach(sparse, 'sparse', 'Other information ' * 80 + ' Quasarword appears once.', compile_now=False)
        self.attach(dense, 'dense', '\n\n'.join(f'Block {i}. ' + 'Quasarword ' * 170 for i in range(32)), compile_now=False)
        expected = {dense, sparse}
        self.assertEqual({item['id'] for item in self.call('search', query='Quasarword', limit=2)['results']}, expected)
        for action, detail in (('context', {}), ('search', {'detail': 'evidence'})):
            source_matches = importlib.import_module('source_matches')
            with patch.object(source_matches, 'read_body', wraps=source_matches.read_body) as reader:
                result = self.call(action, query='Quasarword', limit=2, max_bytes=64000, **detail)
            self.assertLessEqual(reader.call_count, 6)
            items = result['items' if action == 'context' else 'results']
            self.assertEqual({item['node_id'] for item in items}, expected)
            self.assertTrue(all(item['source_chunk_matches'] for item in items))
            self.assertFalse(result['has_more'])
            first = self.call(action, query='Quasarword', limit=1, max_bytes=64000, **detail)
            cursor = first['search_next_cursor'] if action == 'context' else first['next_cursor']
            second = self.call(action, query='Quasarword', limit=1, max_bytes=64000, cursor=cursor, **detail)
            key = 'items' if action == 'context' else 'results'
            self.assertTrue(first['has_more'])
            self.assertFalse(second['has_more'])
            self.assertEqual({item['node_id'] for item in first[key] + second[key]}, expected)

    def test_source_validation_reaches_valid_passages_after_a_damaged_prefix(self):
        node = self.remember('Unrelated long document', 'Prefer short replies.')['id']
        self.attach(node, 'damaged-prefix', '\n\n'.join(f'Block {i}. ' + 'Latequartz ' * 170 for i in range(24)), compile_now=False)
        paths = self.matching_chunk_paths('Latequartz')
        self.assertGreater(len(paths), 9)
        for path in paths[:9]:
            (self.root / path).write_text('Corrupted contents.', encoding='utf-8')
        for action, detail in (('context', {}), ('search', {'detail': 'evidence'})):
            result = self.call(action, query='Latequartz', limit=1, max_bytes=64000, **detail)
            items = result['items' if action == 'context' else 'results']
            self.assertEqual([item['node_id'] for item in items], [node])
            self.assertTrue(items[0]['source_chunk_matches'])
            self.assertFalse(result['has_more'])

    def test_verified_sample_does_not_scan_a_long_damaged_remainder(self):
        node = self.remember('Unrelated sparse proof', 'Prefer short replies.')['id']
        self.attach(node, 'one-valid', '\n\n'.join(f'Block {i}. ' + 'Onevalidquartz ' * 80 for i in range(24)), compile_now=False)
        paths = self.matching_chunk_paths('Onevalidquartz')
        self.assertGreater(len(paths), 8)
        self.assertNotIn(paths[0], paths[1:])
        for path in paths[1:]:
            (self.root / path).write_text('Corrupted contents.', encoding='utf-8')
        source_matches = importlib.import_module('source_matches')
        for action, detail in (('context', {}), ('search', {'detail': 'evidence'})):
            with patch.object(source_matches, 'read_body', wraps=source_matches.read_body) as reader:
                result = self.call(action, query='Onevalidquartz', limit=1, max_bytes=64000, **detail)
            items = result['items' if action == 'context' else 'results']
            self.assertEqual([item['node_id'] for item in items], [node])
            self.assertLessEqual(reader.call_count, 8)

    def test_attached_references_invalidate_uncompiled_and_stale_inspectors(self):
        for compiled in (False, True):
            with self.subTest(compiled=compiled):
                node = self.remember(f'Profile references {compiled}')['id']
                if compiled:
                    self.call('compile', node_id=node)
                def attach(index):
                    return self.call('attach_entity', node_id=node, owning_app_id='crm',
                                     entity_type='contact', entity_id=f'contact_{index}', title=f'Profile {index}')['external_ref']['id']
                initial = self.call('inspect', node_id=node, detail='sources')['node']
                first = attach(1)
                before = self.call('inspect', node_id=node, detail='sources', limit=1)
                self.assertNotEqual(initial['state_revision'], before['node']['state_revision'])
                second = attach(2)
                paged = self.call('inspect', node_id=node, detail='sources', limit=1)
                third = attach(3)
                after = self.call('inspect', node_id=node, detail='sources')['node']
                self.assertEqual(before['node']['updated_at'], after['updated_at'])
                self.assertNotEqual(before['node']['state_revision'], after['state_revision'])
                self.assertEqual({item['id'] for item in after['sources']}, {first, second, third})
                repeated = self.call('inspect', node_id=node, detail='card')['node']
                self.assertEqual(after['state_revision'], repeated['state_revision'])
                with self.assertRaisesRegex(ValueError, 'stale cursor'):
                    self.call('inspect', node_id=node, detail='sources', limit=1, cursor=paged['next_cursor'])

    def test_evidence_budget_continuation_accounts_for_rejected_positions(self):
        for index in range(8):
            node = self.remember(f'Unrelated budget {index}', 'Prefer short replies.')
            self.attach(node['id'], f'budget-{index}', f'Budgetquartz is the unique evidence word {index}.')
        indexed = self.call('search', query='Budgetquartz', limit=8)['results']
        rejected = indexed[0]['id']
        self.chunk_path(rejected).unlink()
        expected = {item['id'] for item in indexed[1:]}
        seen, cursor, stops = set(), None, set()
        for _ in range(15):
            page = self.call('search', query='Budgetquartz', detail='evidence', limit=5,
                             max_bytes=3500, cursor=cursor)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode()), 3500)
            ids = {item['node_id'] for item in page['results']}
            self.assertFalse(ids & seen)
            seen |= ids
            stops.add(page['stop_reason'])
            cursor = page['next_cursor']
            if not page['has_more']:
                break
        self.assertIsNone(cursor)
        self.assertEqual(seen, expected)
        self.assertIn('budget', stops)

    def test_inspector_state_revision_changes_when_evidence_changes_without_fact_edit(self):
        node = self.remember('Annual contract', 'The annual contract costs 1200 euro.')
        self.attach(node['id'], 'contract', 'The annual contract costs 1200 euro.')
        before = self.call('inspect', node_id=node['id'])['node']
        repeated = self.call('inspect', node_id=node['id'], detail='evidence')['node']
        self.assertEqual(before['state_revision'], repeated['state_revision'])
        self.assertEqual(repeated['verification'], 'verified')
        self.attach(node['id'], 'contract', 'The annual contract costs 9000 euro.', compile_now=False)
        pending = self.call('inspect', node_id=node['id'])['node']
        self.assertEqual(pending['updated_at'], before['updated_at'])
        self.assertNotEqual(pending['state_revision'], before['state_revision'])
        self.call('compile', node_id=node['id'])
        after = self.call('inspect', node_id=node['id'], detail='evidence')['node']
        self.assertEqual(after['updated_at'], before['updated_at'])
        self.assertNotEqual(after['state_revision'], pending['state_revision'])
        self.assertEqual(after['verification'], 'conflict')
        card = self.call('inspect', node_id=node['id'])['node']
        self.assertEqual(card['state_revision'], after['state_revision'])
