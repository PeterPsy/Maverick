"""Approved Mail display reads from the local read store, never send/OAuth/sync."""
import json
from pathlib import Path

from core.app_sdk.display_models import conditional_display_response, project_display_model
from store import list_connections, list_folders, list_threads, count_threads, get_thread, get_message

SCHEMAS = json.loads((Path(__file__).resolve().parents[1] / 'pwa_read_models.v1.json').read_text())


def read_model(data_root, body):
    kind = body.get('kind')
    if kind not in SCHEMAS:
        raise ValueError('Unsupported Mail display read.')
    if kind == 'mailboxes':
        source = {'items': list_connections(data_root), 'folders': list_folders(data_root)}
    elif kind == 'threads':
        limit = min(200, max(1, int(body.get('max_threads', 50))))
        offset = min(100000, max(0, int(body.get('offset', 0))))
        query = {key: body[key] for key in ('mailbox', 'mailbox_scopes', 'connection_id', 'query') if key in body}
        query.update(max_threads=limit, offset=offset)
        source = {'items': list_threads(data_root, query), 'limit': limit, 'offset': offset, 'total_count': count_threads(data_root, query)}
    else:
        limit = min(1000000, max(1, int(body.get('max_body_chars', 100000))))
        if kind == 'thread':
            source = {'thread': get_thread(data_root, str(body.get('thread_id') or ''), limit, 0)}
        else:
            source = {'message': get_message(data_root, str(body.get('message_id') or ''), limit, 0)}
    # This projection serves text, not deliberately zero-length rich HTML.
    messages = (source.get('thread') or {}).get('messages', []) if kind == 'thread' else [source.get('message')] if kind == 'message' else []
    for message in messages:
        if message:
            message['body_truncated'] = bool(message.get('body_source_truncated') or message.get('body_text_truncated'))
            message['body_html_truncated'] = False
    payload = {'kind': kind, 'data': project_display_model(source, SCHEMAS[kind])}
    return conditional_display_response(payload, body.get('known_revision'))
