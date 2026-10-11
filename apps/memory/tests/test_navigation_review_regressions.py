"""Review cases for critical continuation, source integrity and inspector state."""

import json

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
