from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.apps import runtime_requests
from core.apps.runtime_request_actor import runtime_request_actor
from core.authorization.errors import AuthorizationError


class RuntimeRequestReplayTests(unittest.TestCase):
    def test_deferred_actor_is_stable_and_cannot_override_authenticated_actor(self):
        self.assertEqual(runtime_request_actor({'on_behalf_of_user_id': 'owner'}, None), 'owner')
        self.assertEqual(runtime_request_actor({'on_behalf_of_user_id': 'owner'}, 'owner'), 'owner')
        with self.assertRaises(AuthorizationError):
            runtime_request_actor({'on_behalf_of_user_id': 'other'}, 'owner')
        with self.assertRaises(AuthorizationError):
            runtime_request_actor({'on_behalf_of_user_id': []}, None)

    def test_admitted_stream_replays_callback_without_new_profile_admission_or_turn(self):
        request = {'request_id':'request', 'create_stream':True,'idempotency_key':'key', 'on_behalf_of_user_id':'owner',
                   'callback':{'action':'started'},'input_text':'work','agent_id':'chat'}
        stream = SimpleNamespace(actor_id='owner',request_id='request',request_fingerprint=runtime_requests._runtime_request_fingerprint(request),
                                 status='completed',session_id='chat',turn_id='turn',stream_id='stream')
        state = SimpleNamespace(runtime_store=Mock())
        state.runtime_store.find_app_stream_by_key.return_value=stream
        with patch.object(runtime_requests,'_preflight_runtime_request_before_persistence') as preflight, \
             patch.object(runtime_requests,'submit_runtime_turn_async') as submit, \
             patch.object(runtime_requests,'_invoke_runtime_request_callback',return_value={'status_code':200}) as callback:
            result = runtime_requests._apply_one_runtime_request(state,request=request,workspace_id='default',app_id='consumer',
                source_root=Path('/app'),backend_entrypoint='backend.py',data_root='/data',parsed=SimpleNamespace(),start_path=Path('/repo'))
        self.assertTrue(result['idempotent_replay'])
        self.assertEqual(result['runtime_session_id'],'chat')
        self.assertEqual(callback.call_args.kwargs['status'],'completed')
        preflight.assert_not_called()
        submit.assert_not_called()

    def test_replay_callback_failure_does_not_fail_an_existing_turn(self):
        from core.apps.runtime_request_replay import replay_runtime_request
        request = {'request_id':'request','callback':{'action':'started'}}
        stream = SimpleNamespace(actor_id='owner',request_id='request',request_fingerprint=runtime_requests._runtime_request_fingerprint(request),
                                 status='running',session_id='chat',turn_id='turn',stream_id='stream')
        with patch.object(runtime_requests,'_invoke_runtime_request_callback',side_effect=RuntimeError('unavailable')):
            result = replay_runtime_request(SimpleNamespace(),stream=stream,request=request,actor_id='owner')
        self.assertEqual(result['status'],'running')
        self.assertEqual(result['callback_status_code'],500)
