"""Numeric validation applies to complete candidate propositions."""

import unittest
from unittest.mock import patch

from memory_test_fixture import MemoryTestCase


class PropositionRegressions(MemoryTestCase):
    def attach(self, fact, evidence, key):
        node = self.call('remember', title=f'Proposition {key}', body=fact)['node']
        return self.call('ingest_source', node_id=node['id'], operation='attach_evidence',
            adapter_id='inline_markdown', source_key=key, title='Evidence',
            body_markdown=evidence, compile_after_ingest=True)

    def test_spaced_arithmetic_cannot_be_certified(self):
        pairs = [('100 / 10', '100 * 10'), ('5 ^ 2', '5 * 2')]
        expressions = ['100 / 10', '100 * 10', '5 ^ 2', '100 + 10', '100 - 10',
            '100 × 10', '100 ÷ 10', '100 % 10', '5 ^\n 2', '5\t*\t2',
            '(100) / (10)', '5 *\n\n2', '100 ∕ 10', '100 ⋅ 10', '5 & 2']
        pairs.extend((expression, expression) for expression in expressions)
        for index, (left, right) in enumerate(pairs):
            with self.subTest(left=left, right=right):
                result = self.attach(f'Il budget annuale del progetto è {left} euro.',
                    f'Il budget annuale del progetto è {right} euro.', f'arithmetic-{index}')
                self.assertEqual(result['compiled']['citations'], [])
                self.assertEqual(result['compiled']['compiled_page']['verification'], 'unverified')
                self.assertEqual(self.call('inspect', detail='full', node_id=result['node']['id'])['node']['citations'], [])

    def test_identifiers_and_locators_do_not_poison_neighboring_evidence(self):
        fact = 'Marco vive a Milano da dieci anni.'
        headers = ['Chat /app/chat/threads/123e4567-e89b-12d3-a456-426614174000 · turn turn-1 · user',
            'Source: contract-2026-a.pdf', 'Source: /reports/contract-2026-a.pdf',
            'Unrecognized quantity: 5e-1.']
        for index, header in enumerate(headers):
            with self.subTest(header=header):
                result = self.attach(fact, f'{header}\n\n{fact}', f'header-{index}')
                self.assertEqual(result['compiled']['compiled_page']['verification'], 'verified')
                self.assertEqual([citation['quote'] for citation in result['compiled']['citations']], [fact])

    def test_arithmetic_after_paragraph_break_cannot_certify_its_prefix(self):
        operators = ['+', '-', '−', '*', '/', '^', '×', '÷', '⁄', '·', '√',
            '%', '&', '∕', '⋅', '±', '∓', '≤', '>=']
        breaks = ['\n\n', '\r\n\r\n', '\n \t\n']
        operands = [('100', '10'), ('100 euro', '10'), ('100 euro', '(10)'), ('(100)', '.5'),
            ('100 euro', 'aliquota')]
        for index, operator in enumerate(operators):
            for offset, (left, right) in enumerate(operands):
                with self.subTest(operator=operator, left=left, right=right):
                    fact = f'Il budget annuale del progetto è {left}.'
                    source = f'{fact[:-1]}{breaks[index % len(breaks)]}{operator} {right}.'
                    result = self.attach(fact, source, f'right-operator-{index}-{offset}')
                    self.assertEqual(result['compiled']['citations'], [])
                    self.assertEqual(result['compiled']['compiled_page']['verification'], 'unverified')

    def test_split_arithmetic_claim_stays_whole_beside_valid_fact(self):
        valid = 'Marco vive a Milano da dieci anni.'
        expressions = ['100\n\n/ 10', '100 euro\n\n* aliquota',
            '100 euro\n\n+ 10', '100 euro\n\n− (10)', '100 euro\n\n- aliquota',
            '(100)\r\n\r\n× (10)', '5 ⋅\n \t\n2', '5 ∕\n\n2']
        for index, expression in enumerate(expressions):
            with self.subTest(expression=expression):
                fact = f'Il budget annuale del progetto è {expression}.'
                result = self.attach(f'{fact}\n\n{valid}', f'{fact}\n\n{valid}', f'whole-claim-{index}')
                self.assertEqual([claim['claim_text'] for claim in result['compiled']['claims']],
                    [fact, valid])
                self.assertEqual([citation['quote'] for citation in result['compiled']['citations']], [valid])
                self.assertNotEqual(result['compiled']['compiled_page']['verification'], 'verified')

    def test_numeric_fact_remains_separate_from_headers_and_following_assertions(self):
        fact = 'Il budget annuale del progetto è 100 euro.'
        sources = [f'Chat /app/chat/threads/123e4567-e89b-12d3-a456-426614174000\n\n{fact}',
            f'{fact}\n\n/app/chat/threads/123e4567-e89b-12d3-a456-426614174000',
            f'{fact}\n\n* Marco vive a Milano da dieci anni.',
            f'{fact[:-1]}\n\nMarco vive a Milano da dieci anni.']
        for index, source in enumerate(sources):
            with self.subTest(source=source):
                result = self.attach(fact, source, f'numeric-neighbors-{index}')
                self.assertEqual(result['compiled']['compiled_page']['verification'], 'verified')
                self.assertEqual([citation['quote'] for citation in result['compiled']['citations']],
                    [fact[:-1] if index == 3 else fact])

    def test_distinct_signed_quantity_is_still_verified(self):
        fact = 'Il budget annuale è 100 euro e il saldo iniziale è -10 euro.'
        result = self.attach(fact, fact, 'signed-quantity')
        self.assertEqual(result['compiled']['compiled_page']['verification'], 'verified')
        self.assertEqual([citation['quote'] for citation in result['compiled']['citations']], [fact])

    def test_expression_crossing_source_chunks_cannot_certify_its_prefix(self):
        fact = 'Il budget annuale del progetto è 100 euro.'
        for index, operator in enumerate(['/', '*', '−']):
            with self.subTest(operator=operator):
                source = 'Preambolo senza dati. ' * 75 + fact[:-1] + '\n\n' + operator + '1' * 1000 + '.'
                result = self.attach(fact, source, f'chunk-expression-{index}')
                self.assertGreater(len(result['compiled']['compile_run']['metadata']['source_chunk_ids']), 1)
                self.assertEqual(result['compiled']['citations'], [])
                self.assertEqual(result['compiled']['compiled_page']['verification'], 'unverified')

    def test_cross_chunk_expression_does_not_block_complete_neighbor(self):
        valid = 'Marco vive a Milano da dieci anni.'
        fact = 'Il budget annuale del progetto è 100 euro.'
        source = 'Preambolo senza dati. ' * 75 + valid + ' ' + fact[:-1] + '\n\n/' + '1' * 1000 + '.'
        result = self.attach(f'{valid} {fact}', source, 'chunk-neighbor')
        self.assertEqual([citation['quote'] for citation in result['compiled']['citations']], [valid])
        self.assertNotEqual(result['compiled']['compiled_page']['verification'], 'verified')

    def test_malformed_numbers_remain_whole_without_blocking_other_propositions(self):
        fact = 'Il tasso annuale del contratto è -. 5%.'
        valid = 'Marco vive a Milano da dieci anni.'
        result = self.attach(f'{fact} {valid}', f'{fact} {valid}', 'mixed-propositions')
        self.assertEqual([claim['claim_text'] for claim in result['compiled']['claims']], [fact, valid])
        self.assertEqual([citation['quote'] for citation in result['compiled']['citations']], [valid])
        self.assertNotEqual(result['compiled']['compiled_page']['verification'], 'verified')

    def test_identifier_spelling_is_preserved_in_candidate_assertions(self):
        facts = ['La sessione 123e4567-e89b-12d3-a456-426614174000 è attiva.',
            'Il documento contract-2026-a.pdf contiene la decisione.']
        for index, fact in enumerate(facts):
            with self.subTest(fact=fact):
                result = self.attach(fact, fact, f'identifier-{index}')
                self.assertEqual(result['compiled']['compiled_page']['verification'], 'verified')
                self.assertEqual([citation['quote'] for citation in result['compiled']['citations']], [fact])
        result = self.attach(facts[1], 'Il documento contract2026a.pdf contiene la decisione.', 'different-locator')
        self.assertEqual(result['compiled']['citations'], [])
        self.assertEqual(result['compiled']['compiled_page']['verification'], 'unverified')
        for index, value in enumerate(['5e-1/kg', '1_000/kg']):
            with self.subTest(quantity=value):
                fact = f'Il tasso annuale del contratto è {value}.'
                result = self.attach(fact, fact, f'unsupported-unit-{index}')
                self.assertEqual(result['compiled']['citations'], [])
                self.assertEqual(result['compiled']['compiled_page']['verification'], 'unverified')

    def test_v6_unverified_uuid_evidence_is_reconsidered(self):
        fact = 'Marco vive a Milano da dieci anni.'
        source = f'Chat /app/chat/threads/123e4567-e89b-12d3-a456-426614174000\n\n{fact}'
        with patch('citation_matching.proposition_texts', side_effect=lambda text: [text]):
            result = self.attach(fact, source, 'legacy-uuid')
        self.assertEqual(result['compiled']['compiled_page']['verification'], 'unverified')
        old_run = result['compiled']['compile_run']['id']
        node_id = result['node']['id']
        with self.database.transaction(self.root) as db:
            db.execute("UPDATE schema_metadata SET value='6' WHERE key='schema_version'")
        self.database.ensure_schema(self.root)
        self.database.ensure_schema(self.root)
        self.assertEqual(len(self.call('jobs_list', status='ready')['jobs']), 1)
        self.call('maintenance')
        inspected = self.call('inspect', detail='full', node_id=node_id)['node']
        self.assertEqual(inspected['compiled_page']['verification'], 'verified')
        self.assertEqual([citation['quote'] for citation in inspected['citations']], [fact])
        self.assertNotEqual(self.call('compile', node_id=node_id)['compile_run']['id'], old_run)

    def test_v6_arithmetic_verification_is_revoked_and_recompiled_once(self):
        with patch('citation_matching.support_relation', return_value='supports'):
            result = self.attach('Il budget annuale del progetto è 100 / 10 euro.',
                'Il budget annuale del progetto è 100 * 10 euro.', 'legacy-arithmetic')
        self.assertEqual(result['compiled']['compiled_page']['verification'], 'verified')
        old_run = result['compiled']['compile_run']['id']
        node_id = result['node']['id']
        with self.database.transaction(self.root) as db:
            db.execute("UPDATE schema_metadata SET value='6' WHERE key='schema_version'")
        self.database.ensure_schema(self.root)
        self.database.ensure_schema(self.root)
        inspected = self.call('inspect', detail='full', node_id=node_id)['node']
        self.assertEqual(inspected['compiled_page']['freshness'], 'stale')
        self.assertEqual(inspected['compiled_page']['verification'], 'unverified')
        self.assertEqual(inspected['citations'], [])
        self.assertEqual(len(self.call('jobs_list', status='ready')['jobs']), 1)
        self.call('maintenance')
        inspected = self.call('inspect', detail='full', node_id=node_id)['node']
        self.assertEqual(inspected['compiled_page']['freshness'], 'fresh')
        self.assertEqual(inspected['compiled_page']['verification'], 'unverified')
        self.assertEqual(inspected['citations'], [])
        compiled = self.call('compile', node_id=node_id)
        self.assertNotEqual(compiled['compile_run']['id'], old_run)
        self.assertTrue(compiled['reused'])

    def test_v7_truncated_verification_is_revoked_and_recompiled_once(self):
        fact = 'Il budget annuale del progetto è 100 euro.'
        source = f'{fact[:-1]}\n\n* 10.'
        with patch('citation_matching.proposition_texts', side_effect=lambda text: text.split('\n\n')):
            result = self.attach(fact, source, 'legacy-paragraph-operator')
        self.assertEqual(result['compiled']['compiled_page']['verification'], 'verified')
        old_run = result['compiled']['compile_run']['id']
        node_id = result['node']['id']
        with self.database.transaction(self.root) as db:
            db.execute("UPDATE schema_metadata SET value='7' WHERE key='schema_version'")
        self.database.ensure_schema(self.root)
        self.database.ensure_schema(self.root)
        inspected = self.call('inspect', detail='full', node_id=node_id)['node']
        self.assertEqual(inspected['compiled_page']['freshness'], 'stale')
        self.assertEqual(inspected['compiled_page']['verification'], 'unverified')
        self.assertEqual(inspected['citations'], [])
        self.assertEqual(len(self.call('jobs_list', status='ready')['jobs']), 1)
        self.call('maintenance')
        inspected = self.call('inspect', detail='full', node_id=node_id)['node']
        self.assertEqual(inspected['compiled_page']['freshness'], 'fresh')
        self.assertEqual(inspected['compiled_page']['verification'], 'unverified')
        self.assertEqual(inspected['citations'], [])
        compiled = self.call('compile', node_id=node_id)
        self.assertNotEqual(compiled['compile_run']['id'], old_run)
        self.assertTrue(compiled['reused'])


if __name__ == '__main__':
    unittest.main()
