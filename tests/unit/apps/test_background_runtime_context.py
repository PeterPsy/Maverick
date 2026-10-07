from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.apps.background_runtime_context import runtime_background_context


class BackgroundRuntimeContextTests(unittest.TestCase):
    def test_context_is_source_owned_bounded_and_includes_orchestration(self):
        timestamp=datetime.now(UTC)
        session=lambda name,source:SimpleNamespace(session_id=name,source_app_id=source,updated_at=timestamp,session_kind='chat_root',thread_visibility='user',project_id='project')
        turn=SimpleNamespace(turn_id='turn',status='completed',input_text='evidence',completed_at=timestamp,updated_at=timestamp,started_at=timestamp,created_at=timestamp)
        store=Mock()
        store.list_sessions.return_value=[session('chat','consumer'),session('foreign','other')]
        store.list_app_streams_for_session.return_value=[SimpleNamespace(source_app_id='consumer',request_id='request',session_id='chat',turn_id='turn',status='completed'),SimpleNamespace(source_app_id='other',request_id='foreign')]
        store.has_turn_with_status.return_value=False
        store.list_recent_turns.return_value=[turn]
        store.find_turn_event.return_value=SimpleNamespace(payload={'output_text':'result'})
        runs=Mock()
        runs.list_runs.return_value=[SimpleNamespace(source_app_id='consumer',status='active',root_runtime_session_id='chat')]
        state=SimpleNamespace(runtime_store=store,inter_agent_store=runs)
        result=runtime_background_context(state,'default','consumer',recovery=True)
        self.assertEqual(result['busy_runtime_session_ids'],['chat'])
        self.assertEqual(result['recent_terminal_exchanges'][0]['output_text'],'result')
        self.assertEqual(result['runtime_request_states'],[{'request_id':'request','session_id':'chat','turn_id':'turn','status':'completed'}])
        store.has_turn_with_status.assert_called_once()
        store.list_recent_turns.assert_called_once_with('chat',limit=10)
        store.reset_mock()
        store.has_turn_with_status.return_value=True
        result=runtime_background_context(state,'default','consumer')
        self.assertNotIn('recent_terminal_exchanges',result)
        store.list_recent_turns.assert_not_called()
