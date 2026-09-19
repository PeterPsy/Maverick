"""Deterministic meeting context and explicitly recorded outcomes, never invented facts."""

import json
from errors import ValidationError
from store import require_text, utc_now, write_event
from .integration_operations import target
from .external_refs import list_external_refs
from .record_graph import record_context, link_records
from .record_mutations import log_activity
from .workflow import _create_workflow_proposal


def meeting_brief(db, payload):
    entity, entity_id = target(db, payload)
    context = record_context(db, {'entity_type': entity, 'id': entity_id})
    record = context['record']
    title = str(record.get('name') or record.get('display_name') or record.get('title') or entity_id)
    lines = [f'# Meeting brief: {title}', '', str(record.get('summary') or record.get('body') or ''), '', '## Related CRM context']
    for link in context['links'][:30]:
        related = link['record']
        lines.append(f"- {link['relationship']}: {related.get('name') or related.get('display_name') or related.get('title') or related['id']}")
    if entity in {'account', 'contact', 'deal'}:
        for table, caption, field in [('tasks', 'Open commitments', 'title'), ('notes', 'Notes', 'body'), ('activities', 'Recent activity', 'subject')]:
            rows = db.execute(f'SELECT * FROM {table} WHERE {entity}_id=? AND deleted_at IS NULL AND archived_at IS NULL ORDER BY updated_at DESC LIMIT 10', (entity_id,)).fetchall()
            lines += ['', '## ' + caption]
            lines.extend('- ' + str(row[field])[:1500] for row in rows if table != 'tasks' or row['status'] == 'open')
    lines += ['', '## Linked app context (snapshots; verify freshness)']
    for ref in context['external_refs'][:30]:
        checked = ref['metadata'].get('last_synced_at', 'not verified')
        lines.append(f"- {ref['source_app_id']}: {ref['title']} — {ref['summary'][:1000]} (updated: {checked})")
    return {'ok': True, 'title': title, 'brief': '\n'.join(lines)[:30000], 'generated_at': utc_now(), 'external_refs': context['external_refs']}


def record_outcome(db, payload):
    db.execute('BEGIN IMMEDIATE')
    entity, entity_id = target(db, payload)
    key = require_text(payload, 'idempotency_key', required=True)
    if len(key) > 160:
        raise ValidationError('Idempotency key is too long.')
    summary = require_text(payload, 'summary', required=True)
    if len(summary) > 30000:
        raise ValidationError('Outcome exceeds 30,000 characters.')
    followups = payload.get('followups', [])
    if not isinstance(followups, list) or len(followups) > 20 or not all(isinstance(f, dict) for f in followups):
        raise ValidationError('Provide at most 20 explicit follow-ups.')
    ref_id = require_text(payload, 'ref_id')
    if ref_id and not any(ref['id'] == ref_id and ref['provider_alias'] == 'calendar' for ref in list_external_refs(db, {'entity_type': entity, 'entity_id': entity_id})):
        raise ValidationError('Meeting must be linked to this CRM record.')
    from .import_sources import digest
    fingerprint = digest([entity, entity_id, summary, followups, ref_id])
    existing = db.execute("SELECT payload_json FROM events WHERE event_type='meeting.outcome_recorded' AND entity_type=? AND entity_id=? AND json_extract(payload_json,'$.idempotency_key')=?", (entity, entity_id, key)).fetchone()
    if existing:
        result = json.loads(existing[0])
        if result['fingerprint'] != fingerprint:
            raise ValidationError('Idempotency key was already used for a different outcome.')
        return {'ok': True, 'replayed': True, **result}
    relation = {entity + '_id': entity_id} if entity in {'account', 'contact', 'deal'} else {}
    activity = log_activity(db, {'subject': 'Meeting outcome', 'body': summary, 'activity_type': 'meeting',
        **relation, 'metadata': {'calendar_ref_id': ref_id, 'crm_context': {'entity_type': entity, 'entity_id': entity_id}}})
    link_records(db, {'source_type': entity, 'source_id': entity_id, 'target_type': 'activity', 'target_id': activity['id'], 'relationship': 'meeting_outcome'})
    proposals = []
    for followup in followups:
        title = require_text(followup, 'title', required=True)
        if len(title) > 300:
            raise ValidationError('Follow-up title is too long.')
        due = require_text(followup, 'due_at')
        if due:
            from .extension_records import validate_field
            validate_field('due_at', 'date', due)
        proposals.append(_create_workflow_proposal(db, 'meeting_followup', entity, entity_id, title,
            {'action': {'type': 'create_task', 'title': title, 'due_at': due, **relation}, 'evidence': {'activity_id': activity['id']}}, source='crm.meetings')['id'])
    result = {'idempotency_key': key, 'fingerprint': fingerprint, 'activity_id': activity['id'], 'proposal_ids': proposals}
    write_event(db, 'meeting.outcome_recorded', entity, entity_id, result)
    return {'ok': True, **result}
