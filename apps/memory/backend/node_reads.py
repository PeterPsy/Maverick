"""Selective, paginated node details; full inspection remains explicit."""

from pathlib import Path

from database import connect, ensure_schema, normalize_limit
from errors import MemoryValidationError
from nodes import inspect_node
from retrieval_cards import node_cards
from retrieval_pages import bounded_page, fingerprint, page_offset, response_budget, retrieval_revision
from node_sections import evidence_items, source_items

DETAILS = {'card', 'content', 'evidence', 'sources', 'history', 'full'}


def read_nodes(data_root: Path, body: dict) -> dict:
    ensure_schema(data_root)
    ids = body.get('node_ids') or [body.get('node_id') or body.get('entity_id') or body.get('id')]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 20 or any(not isinstance(value, str) or not value.strip() for value in ids):
        raise MemoryValidationError('Supply one to twenty node ids.')
    ids = list(dict.fromkeys(value.strip() for value in ids))
    detail = body.get('detail', 'card')
    if detail not in DETAILS:
        raise MemoryValidationError('detail must be card, content, evidence, sources, history or full.')
    if detail != 'card' and len(ids) != 1:
        raise MemoryValidationError('Batch retrieval supports cards; request details for one node at a time.')
    budget = response_budget(body.get('max_bytes'))
    limit = normalize_limit(body.get('limit'), default=20 if detail == 'card' else 10, minimum=1, maximum=50)
    with connect(data_root) as db:
        db.execute('BEGIN')
        binding = fingerprint([ids, detail, body.get('content','node'), body.get('revision_id'), body.get('claim_id'), retrieval_revision(db)])
        offset = page_offset(body.get('cursor'), binding)
        cards = node_cards(db, ids)
        if len(ids) == 1 and not cards:
            raise MemoryValidationError('node not found.')
        if detail == 'card':
            return bounded_page(cards[offset:offset + limit + 1], key='nodes', base={'detail': detail, 'snapshot_id': binding,
                                'unavailable_node_ids': [value for value in ids if value not in {card['id'] for card in cards}]},
                                limit=limit, offset=offset, binding=binding, max_bytes=budget)
        node_id = ids[0]
        base = {'detail': detail, 'snapshot_id': binding, 'node': cards[0]}
        if detail == 'full':
            # Full is intentionally unbudgeted for explicit audit/export callers.
            if body.get('cursor'):
                raise MemoryValidationError('Full inspection does not accept a cursor.')
            return {'detail': detail, 'node': inspect_node(data_root, node_id), 'has_more': False, 'next_cursor': None}
        if detail == 'content':
            chars = normalize_limit(body.get('content_chars'), default=3000, minimum=1, maximum=10000, field_name='content_chars')
            content = body.get('content', 'node')
            if content not in ('node', 'wiki'):
                raise MemoryValidationError('content must be node or wiki.')
            table, field = ('nodes', 'body_text') if content == 'node' else ('wiki_pages', 'body_markdown')
            where = 'id=?' if content == 'node' else "node_id=? AND status='active'"
            if body.get('revision_id'):
                if content != 'node':
                    raise MemoryValidationError('Revision content supports the node body only.')
                row = db.execute("SELECT substr(json_extract(snapshot_json,'$.body_text'),?,?) AS text, length(json_extract(snapshot_json,'$.body_text')) AS total FROM node_revisions WHERE id=? AND node_id=?", (offset+1,chars,body['revision_id'],node_id)).fetchone()
                if row is None:
                    raise MemoryValidationError('revision not found for this node.')
            else:
                row = db.execute(f'SELECT substr({field},?,?) AS text, length({field}) AS total FROM {table} WHERE {where}', (offset+1, chars, node_id)).fetchone()
            text, total = (row['text'], row['total']) if row else ('', 0)
            # Page by characters; UTF-8 byte checks still govern the response.
            from retrieval_pages import byte_count, page_cursor
            while True:
                more = offset+len(text) < total
                payload = {**base, 'content': content, 'text': text, 'content_char_count': total,
                           'content_offset': offset, 'has_more': more,
                           'next_cursor': page_cursor(offset+len(text), binding) if more else None,
                           'stop_reason': 'budget' if row and len(text)<len(row['text']) else 'limit' if more else 'end',
                           'omitted_for_budget': len(row['text'])-len(text) if row else 0}
                if byte_count(payload) <= budget:
                    return payload
                if not text:
                    raise MemoryValidationError('max_bytes is too small for the node card.')
                text = text[:len(text)//2]
        if detail == 'history':
            rows = db.execute('SELECT id,revision,reason,created_at FROM node_revisions WHERE node_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (node_id, limit+1, offset))
            items = [dict(row) for row in rows]
        elif detail == 'sources':
            items = source_items(db,node_id,limit=limit+1,offset=offset)
        else:
            items, state = evidence_items(db,data_root,node_id,limit=limit+1,offset=offset,claim_id=body.get('claim_id'))
            base['node'].update(state)
        key = {'history':'revisions','sources':'sources','evidence':'citations' if body.get('claim_id') else 'claims'}[detail]
        payload = bounded_page(items, key=key, base=base, limit=limit, offset=offset, binding=binding, max_bytes=budget)
        payload['node'][key] = payload.pop(key)
        return payload
