"""Operational screens read actual bounded data without mutations or provider calls."""
from integration_fixture import IntegrationFixture
from errors import ValidationError


class WorkspaceViewTests(IntegrationFixture):
    def test_sidebar_counts_are_active_only_and_do_not_expose_or_mutate_records(self):
        thread = self.call('create_extension_record', entity_type='conversation_thread', title='Private thread')['record']
        expense = self.call('create_extension_record', entity_type='expense', title='Receipt')['record']
        self.call('archive_record', entity_type='conversation_thread', id=thread['id'])
        self.call('delete_record', entity_type='expense', id=expense['id'])
        before = self.business_export()
        result = self.call('workspace_view', view='sidebar')
        self.assertEqual(set(result), {'ok', 'counts'})
        self.assertEqual(set(result['counts']), {'leads', 'contacts', 'accounts', 'deals', 'conversation_threads', 'expenses', 'intelligence_profiles'})
        self.assertEqual(result['counts']['leads'], 0)
        self.assertEqual(result['counts']['contacts'], 1)
        self.assertEqual(result['counts']['conversation_threads'], 0)
        self.assertEqual(result['counts']['expenses'], 0)
        self.assertEqual(before, self.business_export())

    def business_export(self):
        result = self.call('export')['export']
        result.pop('exported_at')
        return result

    def test_tasks_have_disjoint_horizons_and_keep_undated_work(self):
        for title, due in [('Overdue', '2030-01-01'), ('Today', '2030-10-01'), ('Next week', '2030-10-04'), ('Later', '2030-10-20'), ('Unscheduled', '')]:
            self.call('create_task', title=title, due_at=due)
        before = self.business_export()
        expected = {'today': ['Overdue', 'Today'], 'week': ['Next week'], 'month': ['Later'], 'unscheduled': ['Unscheduled']}
        for bucket, titles in expected.items():
            result = self.call('workspace_view', view='tasks', bucket=bucket, day_end='2030-10-01T23:59:59+00:00')
            self.assertEqual([item['title'] for item in result['items']], titles)
        self.assertEqual(before, self.business_export())

    def test_thread_states_pagination_and_archive_filter(self):
        for title, status in [('Reply', 'open'), ('Wait', 'waiting'), ('Done', 'completed')]:
            self.call('create_extension_record', entity_type='conversation_thread', title=title, status=status)
        result = self.call('workspace_view', view='threads', bucket='waiting')
        self.assertEqual([r['title'] for r in result['items']], ['Wait'])
        self.assertEqual(result['summary'], {'reply': 1, 'waiting': 1, 'completed': 1})
        self.assertTrue(self.call('workspace_view', view='threads', limit=1)['has_more'])
        self.call('archive_record', entity_type='conversation_thread', id=result['items'][0]['id'])
        self.assertEqual(self.call('workspace_view', view='threads', bucket='waiting')['total'], 0)

    def test_expenses_do_not_mix_currencies_or_drop_matches_after_first_page(self):
        for currency, amount in [('EUR', 2500), ('USD', 3700), ('EUR', 1000)]:
            self.call('create_extension_record', entity_type='expense', title='Travel', currency=currency, amount_minor=amount)
        result = self.call('workspace_view', view='expenses', limit=1)
        self.assertEqual({r['currency']: r['amount_minor'] for r in result['summary']['currencies']}, {'EUR': 3500, 'USD': 3700})
        self.assertEqual(result['total'], 3)
        self.assertEqual(len(self.call('workspace_view', view='expenses', offset=2, limit=1)['items']), 1)

    def test_calendar_reads_only_live_crm_links_and_keeps_failure_metadata(self):
        self.call('link_external_ref', crm_entity_type='contact', crm_entity_id=self.contact['id'], source_app_id='calendar', source_entity_type='event', source_entity_id='event-1', metadata={'last_error': 'offline'})
        linked = self.call('workspace_view', view='calendar')
        self.assertEqual(linked['total'], 1)
        self.assertEqual(linked['items'][0]['metadata']['last_error'], 'offline')
        self.call('archive_record', entity_type='contact', id=self.contact['id'])
        self.assertEqual(self.call('workspace_view', view='calendar')['total'], 0)

    def test_quality_is_review_only_and_bad_identifiers_are_rejected(self):
        self.call('create_contact', display_name='Incomplete')
        before = self.business_export()
        result = self.call('workspace_view', view='quality', entity_type='contact')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['quality_issue'], 'missing_email')
        self.assertEqual(before, self.business_export())
        for args in [{'view': 'unknown'}, {'view': 'tasks', 'limit': 101}, {'view': 'tasks', 'offset': -1}, {'view': 'quality', 'entity_type': 'events'}, {'view': 'tasks', 'day_end': '2030-01-01'}]:
            with self.assertRaises(ValidationError): self.call('workspace_view', **args)

    def test_calendar_range_is_applied_before_pagination(self):
        for i in range(3):
            self.call('link_external_ref', crm_entity_type='contact', crm_entity_id=self.contact['id'], source_app_id='calendar', source_entity_type='event', source_entity_id=f'event-{i}', metadata={'startTime': f'2030-10-0{i + 1}T09:00:00Z'})
        result = self.call('workspace_view', view='calendar', limit=1, **{'from': '2030-10-02T00:00:00Z', 'until': '2030-10-04T00:00:00Z'})
        self.assertEqual(result['total'], 2)
        self.assertTrue(result['has_more'])
        self.assertEqual(result['items'][0]['source_entity_id'], 'event-1')
        with self.assertRaises(ValidationError):
            self.call('workspace_view', view='calendar', **{'from': '2030-10-02'})

    def test_dashboard_aggregates_real_currencies_and_keeps_existing_records(self):
        self.call('create_deal', name='EUR opportunity', value=2000, currency='EUR', margin_minor=50000)
        self.call('create_deal', name='USD opportunity', value=1000, currency='USD', margin_minor=20000)
        before = self.business_export()
        result = self.call('overview')
        self.assertEqual(result['active_deal_count'], 2)
        self.assertEqual({row['currency']: row['value'] for row in result['pipeline']}, {'EUR': 2000, 'USD': 1000})
        self.assertEqual(result['recent_contacts'][0]['id'], self.contact['id'])
        self.assertEqual(before, self.business_export())

    def test_date_only_tasks_use_local_calendar_day_not_utc_midnight(self):
        self.call('create_task', title='Today locally', due_at='2030-10-01')
        self.call('create_task', title='Tomorrow locally', due_at='2030-10-02')
        for end in ['2030-10-01T23:59:59+14:00', '2030-10-01T23:59:59-10:00']:
            result = self.call('workspace_view', view='tasks', bucket='today', day_end=end)
            self.assertEqual([row['title'] for row in result['items']], ['Today locally'])

    def test_workspace_views_are_discoverable_read_only_helpers(self):
        from domains.action_catalog import operations_manifest, app_events_for_action
        manifest = operations_manifest()
        self.assertIn('crm.workspace_view', manifest['actions'])
        self.assertIn('crm.workspace_view', manifest['ui_helper_actions'])
        self.assertEqual(app_events_for_action('crm.workspace_view'), [])
