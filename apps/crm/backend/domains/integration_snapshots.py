"""Bounded provider projections and safe navigation; never persist raw responses."""

from urllib.parse import quote, urlsplit
from errors import ValidationError
from .integration_catalog import TYPES


def safe_link(value, provider):
    value = str(value or '')
    if value.startswith(f'/app/{provider}/') or value.startswith(f'/app/{provider}?'):
        return value
    url = urlsplit(value)
    if url.scheme == 'https' and url.netloc and not url.username and not url.password:
        return value
    return ''


def reference_snapshot(alias, provider, result, *, task_id=''):
    if not isinstance(result, dict):
        raise ValidationError('Provider returned an invalid reference.')
    ref = result.get('item') or result.get('reference') or result
    if not isinstance(ref, dict) or result.get('exists') is False or ref.get('exists') is False:
        raise ValidationError('Provider record no longer exists.')
    typ = str(ref.get('entity_type') or '')
    entity_id = str(ref.get('entity_id') or ref.get('id') or '')
    if typ not in TYPES[alias] or not entity_id:
        raise ValidationError('Provider returned an invalid reference identity.')
    metadata = {'resolution_status': 'resolved', 'sync_enabled': True}
    data = ref.get('data') or ref.get('safe_fields') or result.get('safe_fields') or {}
    if not isinstance(data, dict):
        raise ValidationError('Invalid provider fields.')
    for key in ('status', 'updated_at', 'revision', 'workspace_relative_path', 'content_type', 'startTime', 'endTime', 'timezone', 'location', 'last_message_at', 'received_at', 'sent_at'):
        if isinstance(data.get(key), (str, int, float, bool)):
            metadata[key] = data[key][:1000] if isinstance(data[key], str) else data[key]
    if alias == 'files':
        metadata['workspace_relative_path'] = str(data.get('workspace_relative_path') or ref.get('workspace_relative_path') or '')
        provenance = ref.get('metadata') if isinstance(ref.get('metadata'), dict) else {}
        for key in ('sha256', 'modified_at', 'source_updated_at'):
            if isinstance(provenance.get(key), str): metadata[key] = provenance[key][:200]
    if alias == 'tasks':
        payload = result.get('payload') or result.get('checklist') or {}
        if not isinstance(payload, dict) or not isinstance(payload.get('sections', []), list):
            raise ValidationError('Provider returned invalid Checklist sections.')
        sections = payload.get('sections', [])
        metadata['sections'] = [{'id': str(s.get('id', '')), 'title': str(s.get('title', ''))[:300]} for s in sections[:50] if isinstance(s, dict)]
        if task_id:
            found = [(s, t) for s in sections if isinstance(s, dict) and isinstance(s.get('tasks', []), list)
                     for t in s.get('tasks', []) if isinstance(t, dict) and t.get('id') == task_id]
            if not found:
                raise ValidationError('Linked Checklist task no longer exists.')
            section, task = found[0]
            metadata.update(task_id=task_id, section_id=section['id'], status=task.get('status') or ('completed' if task.get('checked') else 'pending'))
            ref = {**ref, 'title': task.get('title') or task.get('text') or ref.get('title')}
    deep_link = safe_link(ref.get('deep_link'), provider)
    if not deep_link and ref.get('app_page'):
        deep_link = f"/app/{quote(provider, safe='')}/{str(ref['app_page']).lstrip('/')}"
    metadata['deep_link'] = deep_link or f"/app/{quote(provider, safe='')}"
    return {'source_entity_type': typ, 'source_entity_id': entity_id, 'title': str(ref.get('title') or entity_id)[:500],
            'summary': str(ref.get('summary') or '')[:2000], 'occurred_at': str(metadata.get('startTime') or metadata.get('last_message_at') or metadata.get('received_at') or metadata.get('sent_at') or ''), 'metadata': metadata}


def write_snapshot(item, result):
    kind, body = item['kind'], item['request']['body']
    provider = item['provider_app_id']
    key = {'mail_draft': 'draft', 'calendar_event': 'event', 'document': 'file', 'checklist_task': 'task', 'task_status': 'task'}[kind]
    if not isinstance(result.get(key, result if kind == 'document' else None), dict):
        raise ValidationError('Provider returned an invalid write result.')
    if kind == 'mail_draft':
        draft = result.get('draft', {})
        return reference_snapshot('mail', provider, {'entity_type': 'mail_draft', 'entity_id': draft.get('id'),
            'title': draft.get('subject'), 'summary': 'Draft prepared; review and send in Mail.',
            'deep_link': f"/app/{provider}?draft={quote(str(draft.get('id') or ''), safe='')}"})
    if kind == 'calendar_event':
        event = result.get('event', {})
        return reference_snapshot('calendar', provider, {'entity_type': 'event', 'entity_id': event.get('id'),
            'title': event.get('title'), 'summary': event.get('description', ''), 'safe_fields': event,
            'deep_link': f"/app/{provider}/events/{quote(str(event.get('id') or ''), safe='')}"})
    if kind == 'document':
        file = result.get('file', result)
        entity_id = file.get('file_id') or file.get('id') or file.get('workspace_relative_path')
        return reference_snapshot('files', provider, {'entity_type': 'file', 'entity_id': entity_id,
            'title': file.get('name') or 'CRM document', 'safe_fields': {'workspace_relative_path': body['workspace_relative_path']},
            'deep_link': file.get('deep_link', '')})
    if kind in {'checklist_task', 'task_status'}:
        task = result.get('task', {})
        if not task.get('id'):
            raise ValidationError('Provider returned no task identity.')
        snapshot = reference_snapshot('tasks', provider, {'entity_type': 'checklist', 'entity_id': body['checklist_id'],
            'title': task.get('title') or task.get('text') or body.get('title'), 'deep_link': f"/app/{provider}?checklist={quote(body['checklist_id'], safe='')}"})
        snapshot['metadata'].update(task_id=task['id'], section_id=body['section_id'], status=task.get('status') or ('completed' if task.get('checked') else 'pending'))
        return snapshot
    raise ValidationError('Unsupported provider write result.')
