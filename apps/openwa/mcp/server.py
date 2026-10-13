"""MCP entrypoint for `openwa`."""

from __future__ import annotations

from pathlib import Path
import sys
from core.app_sdk.runtime import emit_json, read_entrypoint_payload
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from service import handle, event
from gateway import GatewayError


payload = read_entrypoint_payload()
tool = str(payload.raw.get('tool_name') or '').split('.')[-1]
if tool == 'openwa_reference_manifest':
    emit_json({'app_id': 'openwa', 'reference_manifest': {'entity_types': []}})
else:
    actions = {'openwa_' + name.replace('.', '_'): name for name in ('status', 'sessions.list', 'session.get', 'session.qr', 'chats.list', 'contacts.list', 'messages.list', 'messages.image', 'webhooks.list', 'templates.list', 'session.create', 'session.start', 'session.stop', 'session.logout', 'session.pair', 'messages.send', 'messages.reply')}
    try:
        result = handle(payload, {**payload.arguments, 'action': actions.get(tool, 'unknown')})
        emit_json({'ok': True, **result})
    except GatewayError as error:
        result = {'ok': False, 'error': error.code, 'detail': str(error), 'status_code': error.status}
        if tool in {'openwa_messages_send', 'openwa_messages_reply'} and error.uncertain_send:
            result['app_events'] = [event('notifications')]
        emit_json(result)
