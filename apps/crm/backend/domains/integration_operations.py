"""Approved, immutable requests through core-governed dependency callbacks."""

import json

from errors import NotFoundError, ValidationError
from store import get_record, new_id, require_text, row_to_dict, utc_now, write_event
from .integration_catalog import KINDS, SAFE_RETRY, SEARCH_ACTIONS, RESOLVE_ACTIONS, TYPES, build_write, selected_provider
from .workflow import _create_workflow_proposal, _workflow_proposal


def target(db, payload):
    entity = require_text(payload, 'entity_type', required=True)
    entity_id = require_text(payload, 'entity_id', required=True)
    if entity.startswith('campaign'):
        raise ValidationError('Campaign integrations are excluded.')
    get_record(db, entity, entity_id)
    return entity, entity_id


def operation(db, operation_id):
    row = db.execute('SELECT * FROM integration_operations WHERE id=?', (operation_id,)).fetchone()
    if not row:
        raise NotFoundError('Integration operation not found.')
    item = row_to_dict(row)
    if item['proposal_id']:
        item['approval_status'] = _workflow_proposal(db, item['proposal_id'])['status']
    return item


def insert(db, entity, entity_id, kind, alias, provider, request, operation_id=None):
    operation_id = operation_id or new_id('iop')
    now = utc_now()
    db.execute('INSERT INTO integration_operations(id, entity_type, entity_id, kind, provider_alias, provider_app_id, request_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
               (operation_id, entity, entity_id, kind, alias, provider, json.dumps(request), 'prepared', now, now))
    return operation_id


def prepare(db, payload):
    entity, entity_id = target(db, payload)
    operation_id = new_id('iop')
    kind, alias, provider, request = build_write(db, payload, operation_id, entity, entity_id)
    insert(db, entity, entity_id, kind, alias, provider, request, operation_id)
    proposal = _create_workflow_proposal(db, 'provider_operation', entity, entity_id,
        f"{kind.replace('_', ' ').title()} · {provider}",
        {'action': {'type': 'provider_operation', 'operation_id': operation_id},
         'provider_app_id': provider, 'request': request['body'], 'sending': False}, source='crm.integrations')
    db.execute('UPDATE integration_operations SET proposal_id=? WHERE id=?', (proposal['id'], operation_id))
    return {'ok': True, 'operation': operation(db, operation_id), 'workflow_proposal': proposal}


def dispatch(db, payload, *, retry=False):
    db.execute('BEGIN IMMEDIATE')
    item = operation(db, require_text(payload, 'id', required=True))
    get_record(db, item['entity_type'], item['entity_id'])
    if item['status'] == 'succeeded':
        return {'ok': True, 'operation': item, 'replayed': True}
    if item['status'] == 'running' and not retry:
        return {'ok': True, 'operation': item, 'replayed': True}
    if retry:
        if item['kind'] not in SAFE_RETRY or item['status'] not in {'failed', 'uncertain', 'running'}:
            raise ValidationError('This operation cannot be blindly retried. Reconcile the provider identity instead.')
        if item['status'] == 'running':
            age = db.execute("SELECT (julianday('now')-julianday(updated_at))*86400 FROM integration_operations WHERE id=?", (item['id'],)).fetchone()[0]
            if age < 90:
                raise ValidationError('The current attempt is still in flight. Wait before retrying.')
    elif item['status'] != 'prepared':
        raise ValidationError('Use the explicit retry or reconcile action after a failed operation.')
    if selected_provider(db, payload, item['provider_alias']) != item['provider_app_id']:
        raise ValidationError('Provider selection changed. Prepare a new proposal against the selected provider.')
    if item['kind'] in KINDS and item.get('approval_status') != 'approved':
        raise ValidationError('Approve the workflow proposal separately before execution.')
    return start(db, item)


def start(db, item):
    attempt = new_id('attempt')
    db.execute("UPDATE integration_operations SET status='running', attempt_id=?, attempts=attempts+1, updated_at=?, last_error='' WHERE id=?",
               (attempt, utc_now(), item['id']))
    write_event(db, 'integration.requested', item['entity_type'], item['entity_id'], {'operation_id': item['id'], 'kind': item['kind']})
    return {'ok': True, 'operation': operation(db, item['id']), 'dependency_backend_requests': [{
        'request_id': attempt, 'dependency_alias': item['provider_alias'], 'body': item['request']['body'],
        'callback': {'action': 'crm.integration_callback', 'payload': {'operation_id': item['id']}}}]}


def read_request(db, payload, *, kind='search'):
    entity, entity_id = target(db, payload)
    alias = require_text(payload, 'provider_alias', required=True)
    provider = selected_provider(db, payload, alias)
    if alias not in SEARCH_ACTIONS:
        raise ValidationError('This provider does not expose browsable references.')
    if kind == 'search':
        query = require_text(payload, 'query')
        if len(query) > 300:
            raise ValidationError('Search query is too long.')
        body = {'action': SEARCH_ACTIONS[alias], 'query': query, 'limit': 20}
    else:
        typ = require_text(payload, 'source_entity_type', required=True)
        if typ not in TYPES[alias]:
            raise ValidationError('Unsupported provider entity type.')
        body = {'action': RESOLVE_ACTIONS[alias], 'entity_type': typ,
                'entity_id': require_text(payload, 'source_entity_id', required=True)}
    ref_id = require_text(payload, 'ref_id')
    if ref_id:
        linked = db.execute('SELECT * FROM external_refs WHERE id=? AND deleted_at IS NULL', (ref_id,)).fetchone()
        if not linked or (linked['crm_entity_type'], linked['crm_entity_id'], linked['source_app_id'], linked['source_entity_type'], linked['source_entity_id']) != (entity, entity_id, provider, body.get('entity_type'), body.get('entity_id')):
            raise ValidationError('Reference does not match this CRM target and provider identity.')
    request = {'body': body, 'ref_id': ref_id}
    if kind == 'reconcile':
        original = operation(db, require_text(payload, 'original_operation_id', required=True))
        if original['status'] not in {'uncertain', 'running'} or original['provider_app_id'] != provider or (original['entity_type'], original['entity_id']) != (entity, entity_id):
            raise ValidationError('Only an uncertain operation for this record/provider can be reconciled.')
        expected = {'mail_draft': 'mail_draft', 'calendar_event': 'event', 'document': 'file', 'checklist_task': 'checklist'}.get(original['kind'])
        if body['entity_type'] != expected:
            raise ValidationError('Reconciliation requires the expected provider record type.')
        # A checklist identity alone cannot prove which task a timed-out add created.
        if original['kind'] == 'checklist_task':
            request['task_id'] = require_text(payload, 'task_id', required=True)
        request['original_operation_id'] = original['id']
    op_id = insert(db, entity, entity_id, kind, alias, provider, request)
    return start(db, operation(db, op_id))


def list_operations(db, payload):
    entity, entity_id = target(db, payload)
    rows = db.execute("SELECT id FROM integration_operations WHERE entity_type=? AND entity_id=? AND kind != 'search' AND NOT (kind IN ('refresh','resolve') AND status='succeeded') ORDER BY created_at DESC, id LIMIT 40", (entity, entity_id)).fetchall()
    proposals = [row_to_dict(row) for row in db.execute('SELECT * FROM workflow_proposals WHERE entity_type=? AND entity_id=? ORDER BY updated_at DESC LIMIT 40', (entity, entity_id))]
    return {'ok': True, 'operations': [operation(db, row['id']) for row in rows], 'proposals': proposals}
