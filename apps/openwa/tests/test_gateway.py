"""Authorization, transport and sending semantics at the native adapter boundary."""
from pathlib import Path
from types import SimpleNamespace
import json
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from actions import perform
from gateway import Gateway, GatewayError, normalize_origin, _connection, check_readiness
from service import handle
from state import configuration, notify, notifications, dismiss

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.payload = SimpleNamespace(data_root=self.temp.name, user_id='alice', platform_role='admin', body={}, raw={'app_secrets': {'openwa-api-key': 'test-secret'}})

    def test_origin_rejects_credentials_and_private_cleartext_destinations(self):
        for url in ['http://10.0.0.1', 'http://127.0.0.1:8000', 'https://key:password@example.com', 'https://example.com?key=secret', 'https://example.com/api/other', 'https://localhost', 'https://[invalid', 'https://exam\nple.com']:
            with self.subTest(url=url), self.assertRaises(GatewayError): normalize_origin(url)
        self.assertEqual(normalize_origin('https://example.com/api'), 'https://example.com')

    def test_private_dns_fails_before_opening_socket(self):
        with patch('gateway.socket.getaddrinfo', return_value=[(2,1,6,'',('169.254.169.254',443))]), self.assertRaises(GatewayError):
            _connection('https://example.com')

    def test_sends_retain_key_across_retry(self):
        transport=MagicMock()
        body={'session_id':'session-1','chat_id':'39123456789@c.us','text':'Hello','idempotency_key':'request-abcdefghijkl'}
        perform(transport,'messages.send',body)
        perform(transport,'messages.send',body)
        self.assertEqual(transport.request.call_count,2)
        self.assertEqual(transport.request.call_args.kwargs['idempotency_key'],'request-abcdefghijkl')
        self.assertEqual(transport.request.call_args.args[2],{'chatId':'39123456789@c.us','text':'Hello'})

    def test_missing_idempotency_and_path_traversal_never_send(self):
        transport=MagicMock()
        for body in [{'session_id':'../other','chat_id':'123@c.us','text':'Hello','idempotency_key':'request-abcdefghijkl'}, {'session_id':'session-1','chat_id':'123@c.us','text':'Hello'}]:
            with self.assertRaises(GatewayError):perform(transport,'messages.send',body)
        transport.request.assert_not_called()

    def test_cold_start_timeout_returns_live_job_state(self):
        transport=MagicMock()
        transport.request.side_effect=[GatewayError('Timed out',503),{'id':'session-1','status':'initializing','engineLoaded':True}]
        result=perform(transport,'session.start',{'session_id':'session-1'})
        self.assertEqual(result['status'],'initializing')
        self.assertEqual(transport.request.call_args.args,('GET','/sessions/session-1'))

    def test_admin_connection_uses_core_secret_without_storing_it(self):
        self.payload.body={'action':'connection.save','url':'https://example.com'}
        with patch('service.Gateway') as gateway:
            gateway.return_value.request.return_value={'valid':True,'role':'operator','engineType':'whatsapp-web.js'}
            result=handle(self.payload)
        gateway.assert_called_once_with('https://example.com','test-secret')
        self.assertNotIn('platform_secret_writes',result)
        self.assertNotIn('test-secret',json.dumps(configuration(self.temp.name)))
        self.assertNotIn('test-secret',json.dumps(result))

    def test_raw_key_configuration_is_rejected_before_provider_call(self):
        self.payload.body={'action':'connection.save','url':'https://example.com','api_key':'new-secret'}
        with patch('service.Gateway') as gateway, self.assertRaises(GatewayError):handle(self.payload)
        gateway.assert_not_called()

    def test_connection_denies_untrusted_actor_and_member_configuration(self):
        self.payload.body={'action':'connection.save','url':'https://example.com','api_key':'new-secret'}
        self.payload.platform_role='member'
        with self.assertRaises(GatewayError):handle(self.payload)
        self.payload.user_id=None
        with self.assertRaises(GatewayError):handle(self.payload)

    def test_notifications_are_deduplicated_and_user_scoped(self):
        for _ in range(2):notify(self.temp.name,'alice','send-a','Check send','A failed send','session-1')
        self.assertEqual(notifications(self.temp.name,'alice',0,50)['total'],1)
        self.assertEqual(notifications(self.temp.name,'bob',0,50)['total'],0)
        identifier=notifications(self.temp.name,'alice',0,50)['notifications'][0]['id']
        notify(self.temp.name,'bob','send-a','Check send','Bob failed send','session-1')
        self.assertEqual(notifications(self.temp.name,'bob',0,50)['total'],1)
        dismiss(self.temp.name,'bob',identifier)
        self.assertEqual(notifications(self.temp.name,'alice',0,50)['total'],1)
        self.assertEqual(notifications(self.temp.name,'bob',0,50)['total'],1)
        dismiss(self.temp.name,'alice',identifier);dismiss(self.temp.name,'alice',identifier)
        self.assertEqual(notifications(self.temp.name,'alice',0,50)['total'],0)

    def test_upstream_error_does_not_echo_sensitive_payload(self):
        response=MagicMock(status=401)
        response.read.return_value=b'{"error":"secret-key-goes-here","code":"private-key"}'
        conn=MagicMock();conn.getresponse.return_value=response
        with patch('gateway._connection',return_value=conn), self.assertRaises(GatewayError) as error:
            Gateway('https://example.com','private-key').request('GET','/sessions')
        self.assertNotIn('secret-key',str(error.exception));self.assertNotIn('private-key',str(error.exception))
        self.assertNotIn('private-key',error.exception.code)
        conn.close.assert_called_once()

    def test_resource_pages_bound_unpaginated_upstream_lists(self):
        transport=MagicMock()
        transport.request.return_value=[{'id':str(i)} for i in range(250)]
        rows=perform(transport,'templates.list',{'session_id':'session-1','limit':50,'offset':100})
        self.assertEqual(len(rows),50)
        self.assertEqual(rows[0]['id'],'100')

    def test_reply_maps_whatsapp_quote_and_preserves_authorized_text(self):
        transport=MagicMock()
        body={'session_id':'session-1','chat_id':'123@c.us','text':'  Hello\n','message_id':'false_123@c.us_ABCD','idempotency_key':'reply-abcdefghijkl'}
        perform(transport,'messages.reply',body)
        self.assertEqual(transport.request.call_args.args,('POST','/sessions/session-1/messages/reply',{
            'chatId':'123@c.us','text':'  Hello\n','quotedMessageId':'false_123@c.us_ABCD'}))

    def test_uncertain_send_creates_actor_scoped_notice(self):
        self.payload.body={'action':'messages.send','session_id':'session-1','chat_id':'123@c.us','text':'Hello','idempotency_key':'request-abcdefghijkl'}
        with patch('service.Gateway') as gateway:
            gateway.return_value.request.side_effect=GatewayError('Delivery uncertain',503)
            with self.assertRaises(GatewayError):handle(self.payload)
        self.assertEqual(notifications(self.temp.name,'alice',0,50)['total'],1)
        self.assertEqual(notifications(self.temp.name,'bob',0,50)['total'],0)

    def test_idempotency_conflicts_preserve_only_recognized_codes(self):
        for code in ['IDEMPOTENCY_KEY_IN_PROGRESS', 'IDEMPOTENCY_OUTCOME_UNKNOWN', 'secret-key']:
            with self.subTest(code=code):
                response = MagicMock(status=409)
                response.read.return_value = json.dumps({'code': code, 'message': 'private-key'}).encode()
                conn = MagicMock()
                conn.getresponse.return_value = response
                with patch('gateway._connection', return_value=conn), self.assertRaises(GatewayError) as error:
                    Gateway('https://example.com', 'private-key').request('POST', '/sessions/s/messages/send-text')
                self.assertEqual(error.exception.code, code if code.startswith('IDEMPOTENCY_') else 'gateway_error')
                self.assertNotIn('private-key', str(error.exception))

    def test_unknown_conflict_notifies_once_but_in_progress_does_not(self):
        self.payload.body = {'action': 'messages.reply', 'session_id': 'session-1', 'chat_id': '123@c.us',
                             'text': 'Hello', 'message_id': 'quote-1', 'idempotency_key': 'request-abcdefghijkl'}
        with patch('service.Gateway') as gateway:
            gateway.return_value.request.side_effect = GatewayError('Still running', 409, 'IDEMPOTENCY_KEY_IN_PROGRESS')
            with self.assertRaises(GatewayError):
                handle(self.payload)
            self.assertEqual(notifications(self.temp.name, 'alice', 0, 50)['total'], 0)
            gateway.return_value.request.side_effect = GatewayError('Check the chat', 409, 'IDEMPOTENCY_OUTCOME_UNKNOWN')
            for _ in range(2):
                with self.assertRaises(GatewayError):
                    handle(self.payload)
        self.assertEqual(notifications(self.temp.name, 'alice', 0, 50)['total'], 1)
        self.assertEqual(notifications(self.temp.name, 'bob', 0, 50)['total'], 0)

    def test_missing_credentials_do_not_create_an_uncertain_send_notice(self):
        self.payload.body = {'action': 'messages.send', 'session_id': 'session-1', 'chat_id': '123@c.us',
                             'text': 'Hello', 'idempotency_key': 'request-abcdefghijkl'}
        self.payload.raw['app_secrets'] = {}
        with self.assertRaises(GatewayError) as error:
            handle(self.payload)
        self.assertEqual(error.exception.code, 'connection_required')
        self.assertEqual(notifications(self.temp.name, 'alice', 0, 50)['total'], 0)

    def test_send_scope_is_stable_and_separates_actors_workspaces_and_gateways(self):
        first = handle(self.payload)['send_scope']
        self.assertEqual(first, handle(self.payload)['send_scope'])
        self.payload.user_id = 'bob'
        self.assertNotEqual(first, handle(self.payload)['send_scope'])
        self.payload.user_id = 'alice'
        with tempfile.TemporaryDirectory() as other:
            self.payload.data_root = other
            self.assertNotEqual(first, handle(self.payload)['send_scope'])
        self.payload.data_root = self.temp.name
        from state import save_configuration
        save_configuration(self.temp.name, {'url': 'https://example.com', 'configured': True})
        self.assertNotEqual(first, handle(self.payload)['send_scope'])

    def test_readiness_is_credential_free_and_rejects_unready_provider(self):
        for status, body, succeeds in [(200, {'status': 'ok'}, True), (503, {'status': 'error'}, False),
                                      (200, {'status': 'error'}, False), (200, [], False)]:
            with self.subTest(status=status, body=body):
                response = MagicMock(status=status)
                response.read.return_value = json.dumps(body).encode()
                conn = MagicMock()
                conn.getresponse.return_value = response
                with patch('gateway._connection', return_value=conn):
                    if succeeds:
                        check_readiness('https://example.com')
                    else:
                        with self.assertRaises(GatewayError):
                            check_readiness('https://example.com')
                self.assertNotIn('X-API-Key', conn.request.call_args.kwargs['headers'])
                self.assertEqual(conn.request.call_args.args[:2], ('GET', '/api/health/ready'))
                conn.close.assert_called_once()

    def test_readiness_reports_unreachable_provider(self):
        conn = MagicMock()
        conn.request.side_effect = ConnectionRefusedError()
        with patch('gateway._connection', return_value=conn), self.assertRaises(GatewayError) as error:
            check_readiness('http://127.0.0.1:2785')
        self.assertEqual(error.exception.status, 503)
        conn.close.assert_called_once()

    def test_uncertain_conflicts_emit_notification_events_on_every_entrypoint(self):
        app = Path(__file__).resolve().parents[1]
        self.payload.arguments = {'action': 'messages.send'}
        self.payload.body = {'action': 'messages.send'}
        self.payload.raw['tool_name'] = 'openwa_messages_send'
        for entrypoint in ['backend/app_backend.py', 'cli/app_cli.py', 'mcp/server.py']:
            for code in ['IDEMPOTENCY_OUTCOME_UNKNOWN', 'IDEMPOTENCY_KEY_IN_PROGRESS']:
                with self.subTest(entrypoint=entrypoint, code=code), \
                     patch('core.app_sdk.runtime.read_entrypoint_payload', return_value=self.payload), \
                     patch('core.app_sdk.runtime.emit_json') as emit, \
                     patch('service.handle', side_effect=GatewayError('Check chat', 409, code)):
                    runpy.run_path(str(app / entrypoint), run_name='__main__')
                result = emit.call_args.args[0]
                if code == 'IDEMPOTENCY_OUTCOME_UNKNOWN':
                    self.assertEqual(result['app_events'], [{'type': 'loopino.app.data-changed', 'resource': 'notifications'}])
                else:
                    self.assertNotIn('app_events', result)

if __name__=='__main__':unittest.main()
