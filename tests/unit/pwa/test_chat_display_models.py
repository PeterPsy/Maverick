from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock, patch
from core.runtime.display_models import completed_message_display, thread_display_page


class ChatDisplayTest(TestCase):
    def test_completed_only_no_provider_or_tool_payload(self):
        date = datetime(2026, 9, 5, tzinfo=timezone.utc)
        store = Mock()
        store.list_recent_turns.return_value = [NS(turn_id='done', status='completed', input_text='Hello', created_at=date), NS(turn_id='active', status='active')]
        store.list_recent_events.return_value = [
            NS(turn_id='done', event_id='e1', event_type='runtime.output.final', created_at=date, payload={'text':'World', 'token':'secret', 'provider_state':{'secret':1}}),
            NS(turn_id='done', event_type='runtime.tool.result', payload={'text':'secret tool'}),
            NS(turn_id='active', event_type='runtime.output.final', payload={'text':'partial'}),
        ]
        first = completed_message_display(store, 'session')
        messages = first['payload']['data']['messages']
        self.assertEqual([item['text'] for item in messages], ['Hello','World'])
        self.assertNotIn('secret', str(first))
        self.assertEqual(completed_message_display(store,'session',first['revision']), {'revision':first['revision'], 'not_modified':True})
        store.list_recent_turns.assert_called_with('session', limit=50)
        store.list_recent_events.assert_called_with('session', limit=5000)

    def test_thread_display_strips_admission_and_stable_revision(self):
        page = {'threads':[{'thread_id':'t','runtime_session_id':'s','title':'Name','availability':'free','system_prompt':'secret','provider_id':'private'}]}
        first = thread_display_page(page)
        self.assertEqual(first['payload']['data']['threads'], [{'thread_id':'t','runtime_session_id':'s','title':'Name','archived':False}])
        page['threads'][0]['availability']='busy'
        self.assertEqual(thread_display_page(page,first['revision'])['not_modified'],True)

    def test_events_display_checks_scope_before_read_and_never_reconciles_provider(self):
        from core.api.runtime_api import _handle_session_events
        state = NS(runtime_store=Mock())
        state.runtime_store.get_session.return_value=NS(workspace_id='other',session_id='s')
        start=Mock()
        _handle_session_events(state, NS(workspace_id='here'), 's', start, start_path='/', query_string='projection=display')
        self.assertEqual(start.call_args[0][0], '404 Not Found')
        state.runtime_store.list_recent_events.assert_not_called()
        state.runtime_store.get_session.return_value=NS(workspace_id='here',session_id='s')
        state.runtime_store.list_recent_events.return_value=[]
        state.runtime_store.list_recent_turns.return_value=[]
        with patch('core.api.runtime_api._visibility_reconciled_session', side_effect=lambda state,session:session), patch('core.api.runtime_api.runtime_session_allows_user_thread', return_value=True), patch('core.api.runtime_api._reconciled_session') as reconcile:
            _handle_session_events(state,NS(workspace_id='here'),'s',start,start_path='/',query_string='projection=display')
            reconcile.assert_not_called()
        self.assertEqual(start.call_args[0][0],'200 OK')
