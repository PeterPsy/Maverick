"""Bounded synchronization of opt-in references; never provider-wide replication."""

import json
from store import row_to_dict, utc_now
from .integration_catalog import RESOLVE_ACTIONS, TYPES, selected_provider
from .integration_operations import insert, operation, start, target
from errors import ValidationError


def refresh(db, payload, *, background=False):
    db.execute('BEGIN IMMEDIATE')
    params = []
    where = 'deleted_at IS NULL'
    # Filter before LIMIT: legacy/unconfigured links must not starve opted-in work.
    where += " AND ((provider_alias='mail' AND source_entity_type IN ('email_thread','email_message','mail_draft','mail_attachment')) OR (provider_alias='calendar' AND source_entity_type='event') OR (provider_alias='files' AND source_entity_type='file') OR (provider_alias='tasks' AND source_entity_type='checklist'))"
    if background:
        where += " AND json_extract(metadata_json, '$.sync_enabled')=1"
    else:
        entity, entity_id = target(db, payload)
        where += ' AND crm_entity_type=? AND crm_entity_id=?'
        params.extend([entity, entity_id])
    # Limit scans as well as remote requests, processing oldest checked links first.
    rows = db.execute(f"SELECT * FROM external_refs WHERE {where} ORDER BY coalesce(json_extract(metadata_json, '$.last_checked_at'), '') LIMIT 200", params).fetchall()
    requests, operations = [], []
    for row in rows:
        ref = row_to_dict(row)
        alias, typ = ref['provider_alias'], ref['source_entity_type']
        if alias not in RESOLVE_ACTIONS or typ not in TYPES[alias]:
            continue
        if background and ref['metadata'].get('last_checked_at'):
            age = db.execute("SELECT (julianday('now')-julianday(?))*86400", (ref['metadata']['last_checked_at'],)).fetchone()[0]
            if age is not None and age < 300:
                continue
        in_flight = db.execute("SELECT 1 FROM integration_operations WHERE kind IN ('resolve','refresh') AND status='running' AND json_extract(request_json, '$.ref_id')=? AND julianday(updated_at)>julianday('now','-90 seconds')", (ref['id'],)).fetchone()
        if in_flight:
            continue
        try:
            if selected_provider(db, payload, alias) != ref['source_app_id']:
                raise ValidationError('Selected provider changed; link retained without synchronizing another app.')
            from .record_lifecycle import record_exists
            if record_exists(db, ref['crm_entity_type'], ref['crm_entity_id']) != 'active':
                metadata = {**ref['metadata'], 'last_checked_at': utc_now()}
                db.execute('UPDATE external_refs SET metadata_json=? WHERE id=?', (json.dumps(metadata), ref['id']))
                continue
        except ValidationError as error:
            metadata = {**ref['metadata'], 'last_checked_at': utc_now(), 'last_error': str(error)}
            db.execute('UPDATE external_refs SET metadata_json=? WHERE id=?', (json.dumps(metadata), ref['id']))
            continue
        request = {'body': {'action': RESOLVE_ACTIONS[alias], 'entity_type': typ, 'entity_id': ref['source_entity_id']}, 'ref_id': ref['id']}
        op_id = insert(db, ref['crm_entity_type'], ref['crm_entity_id'], 'refresh', alias, ref['source_app_id'], request)
        dispatched = start(db, operation(db, op_id))
        requests.extend(dispatched['dependency_backend_requests'])
        operations.append(op_id)
        metadata = {**ref['metadata'], 'last_checked_at': utc_now()}
        db.execute('UPDATE external_refs SET metadata_json=? WHERE id=?', (json.dumps(metadata), ref['id']))
        if len(requests) >= (5 if background else 10):
            break
    return {'ok': True, 'operation_ids': operations, 'dependency_backend_requests': requests}
