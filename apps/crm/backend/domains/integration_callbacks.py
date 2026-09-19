"""Trusted callback ingestion, replay protection and last-good-snapshot preservation."""

import json

from errors import ValidationError
from store import row_to_dict, utc_now, write_event
from .external_refs import link_external_ref
from .integration_catalog import KINDS
from .integration_operations import operation
from .integration_snapshots import reference_snapshot, write_snapshot
from .workflow import _create_workflow_proposal


def complete(db, payload):
    if payload.get('_trusted_surface') != 'dependency_backend_request_callback':
        raise ValidationError('Only the core dependency callback may complete an operation.')
    db.execute('BEGIN IMMEDIATE')
    item = operation(db, str(payload.get('operation_id') or ''))
    if payload.get('request_id') != item['attempt_id'] or payload.get('dependency_alias') != item['provider_alias']:
        raise ValidationError('Callback does not match the current attempt.')
    if item['status'] != 'running':
        return {'ok': True, 'replayed': True}
    wrapper = payload.get('dependency_backend_result') or {}
    result = wrapper.get('json') if isinstance(wrapper.get('json'), dict) else {}
    success = payload.get('dependency_backend_status') == 'completed' and wrapper.get('dependency_provider_app_id') == item['provider_app_id'] and int(wrapper.get('status_code', 500)) < 400 and not result.get('error')
    report = {}
    db.execute('SAVEPOINT callback_result')
    try:
        if not success:
            raise ValidationError('Provider request failed or its result could not be verified. Check the provider before retrying.')
        if item['kind'] == 'search':
            items = result.get('items', result.get('results', []))
            report = {'references': []}
            for ref in items[:20] if isinstance(items, list) else []:
                try:
                    report['references'].append(reference_snapshot(item['provider_alias'], item['provider_app_id'], ref))
                except ValidationError:
                    continue
        elif item['kind'] == 'transcription':
            text = result.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 100000:
                raise ValidationError('Speech did not return a bounded transcript; inspect the source in Speech.')
            proposal = _create_workflow_proposal(db, 'transcript_review', item['entity_type'], item['entity_id'],
                'Review transcription before adding a CRM note',
                {'action': {'type': 'create_note', 'body': text}, 'evidence': {'operation_id': item['id'],
                 'source_ref_id': item['request']['ref_id'], 'provider_app_id': item['provider_app_id'],
                 'job_id': str(result.get('job_id') or '')}}, source='crm.speech')
            report = {'review_proposal_id': proposal['id'], 'text': text, 'job_id': str(result.get('job_id') or '')}
        else:
            if item['kind'] in {'resolve', 'refresh', 'reconcile'}:
                task_id = item['request'].get('task_id', '')
                if item['request'].get('ref_id'):
                    old = db.execute('SELECT metadata_json FROM external_refs WHERE id=? AND deleted_at IS NULL', (item['request']['ref_id'],)).fetchone()
                    if not old:
                        raise ValidationError('Link was removed while refresh was in flight.')
                    task_id = json.loads(old[0]).get('task_id', '')
                snapshot = reference_snapshot(item['provider_alias'], item['provider_app_id'], result, task_id=task_id)
                if item['kind'] == 'reconcile' and task_id:
                    original = operation(db, item['request']['original_operation_id'])
                    if snapshot['metadata'].get('section_id') != original['request']['body']['section_id']:
                        raise ValidationError('The recovered task is in another section.')
                expected = item['request']['body']
                if (snapshot['source_entity_type'], snapshot['source_entity_id']) != (expected['entity_type'], expected['entity_id']):
                    raise ValidationError('Resolved provider identity does not match the request.')
            else:
                snapshot = write_snapshot(item, result)
            report = {'external_ref': save_snapshot(db, item, snapshot)}
            if item['kind'] == 'reconcile':
                original = operation(db, item['request']['original_operation_id'])
                db.execute("UPDATE integration_operations SET status='succeeded', result_json=?, last_error='', updated_at=? WHERE id=?", (json.dumps({'reconciled_by': item['id'], **report}), utc_now(), original['id']))
                mark_applied(db, original)
        db.execute('RELEASE callback_result')
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        db.execute('ROLLBACK TO callback_result')
        db.execute('RELEASE callback_result')
        # No raw provider errors/credentials are retained or echoed to the browser.
        message = str(error) if isinstance(error, ValidationError) else 'Provider returned an invalid response.'
        state = 'uncertain' if item['kind'] in KINDS else 'failed'
        db.execute('UPDATE integration_operations SET status=?, last_error=?, updated_at=? WHERE id=?', (state, message, utc_now(), item['id']))
        mark_ref_error(db, item, message)
        write_event(db, 'integration.failed', item['entity_type'], item['entity_id'], {'operation_id': item['id'], 'status': state})
        return {'ok': True, 'operation_status': state}
    db.execute("UPDATE integration_operations SET status='succeeded', result_json=?, last_error='', updated_at=? WHERE id=?", (json.dumps(report), utc_now(), item['id']))
    mark_applied(db, item)
    write_event(db, 'integration.succeeded', item['entity_type'], item['entity_id'], {'operation_id': item['id'], 'kind': item['kind']})
    return {'ok': True, 'operation_status': 'succeeded'}


def mark_applied(db, item):
    if item['proposal_id']:
        db.execute("UPDATE workflow_proposals SET status='applied', applied_at=?, updated_at=? WHERE id=?", (utc_now(), utc_now(), item['proposal_id']))


def save_snapshot(db, item, snapshot):
    alias = 'files' if item['provider_alias'] == 'file-write' else item['provider_alias']
    ref_id = item['request'].get('ref_id') if item['kind'] in {'resolve', 'refresh', 'task_status'} else ''
    old = db.execute('SELECT * FROM external_refs WHERE id=? AND deleted_at IS NULL', (ref_id,)).fetchone() if ref_id else None
    metadata = {**(json.loads(old['metadata_json']) if old else {}), **snapshot['metadata'],
                'last_synced_at': utc_now(), 'last_checked_at': utc_now(), 'last_error': '', 'integration_operation_id': item['id']}
    link_type = old['link_type'] if old else ('task:' + metadata['task_id'] if metadata.get('task_id') else 'related')
    from .provider_links import PROVIDERS
    return link_external_ref(db, {**snapshot, 'id': ref_id or '', 'crm_entity_type': item['entity_type'], 'crm_entity_id': item['entity_id'],
        'source_app_id': item['provider_app_id'], 'provider_alias': alias, 'source_interface': PROVIDERS[alias], 'link_type': link_type, 'metadata': metadata})


def mark_ref_error(db, item, message):
    ref_id = item['request'].get('ref_id')
    if not ref_id:
        return
    row = db.execute('SELECT * FROM external_refs WHERE id=? AND deleted_at IS NULL', (ref_id,)).fetchone()
    if row:
        metadata = row_to_dict(row)['metadata']
        metadata.update(last_error=message, last_checked_at=utc_now())
        if 'no longer exists' in message:
            metadata['resolution_status'] = 'missing'
        db.execute('UPDATE external_refs SET metadata_json=? WHERE id=?', (json.dumps(metadata), ref_id))
