"""Relationship display schema keeps reviewed values, never workflow authority."""
from unittest.mock import patch

from integration_fixture import IntegrationFixture
from service import handle_action


class DisplayReadModelTests(IntegrationFixture):
    def read(self, **parameters):
        status, result = handle_action(self.root, 'pwa.read_model', parameters)
        self.assertEqual(status, 200)
        return result

    def test_deal_margin_and_conditional_revision(self):
        deal = self.call('create_deal', name='Display deal', value=2000, currency='EUR', margin_minor=50000)['deal']
        query = {'kind': 'records_table', 'entity_type': 'deal', 'limit': 40}
        first = self.read(**query)
        self.assertEqual(first['payload']['data']['records'][0]['record']['margin_minor'], 50000)
        unchanged = self.read(**query, known_revision=first['revision'])
        self.assertTrue(unchanged['not_modified'])
        self.call('update_deal', id=deal['id'], margin_minor=45000)
        changed = self.read(**query, known_revision=first['revision'])
        self.assertNotEqual(changed['revision'], first['revision'])
        self.assertEqual(changed['payload']['data']['records'][0]['record']['margin_minor'], 45000)

    def test_unknown_fields_and_mutation_authority_are_not_projected(self):
        source = {'records': [{'id': 'display', 'entity_type': 'deal', 'title': 'Display', 'record': {
            'id': 'display', 'margin_minor': 50000, 'workflow_proposal': {'approved': True}, 'secret': 'excluded',
        }}], 'columns': [], 'has_more': False, 'next_cursor': '', 'authority': {'can_write': True}}
        with patch('pwa_read_model.records_table', return_value=source):
            model = self.read(kind='records_table', entity_type='deal')['payload']['data']
        self.assertEqual(model['records'][0]['record'], {'id': 'display', 'margin_minor': 50000})
        self.assertNotIn('authority', model)
