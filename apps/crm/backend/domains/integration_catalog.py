"""Closed provider operations and validated request construction; no send surface."""

from datetime import datetime
from pathlib import PurePosixPath

from errors import ValidationError
from store import require_text, row_to_dict
from .provider_links import integration_context

SEARCH_ACTIONS = {'mail': 'mail_reference_search', 'calendar': 'references.search',
                  'files': 'references.search', 'tasks': 'references.search'}
RESOLVE_ACTIONS = {'mail': 'mail_reference_resolve', 'calendar': 'references.resolve',
                   'files': 'references.resolve', 'tasks': 'references.resolve'}
TYPES = {'mail': {'email_thread', 'email_message', 'mail_draft', 'mail_attachment'},
         'calendar': {'event'}, 'files': {'file'}, 'tasks': {'checklist'}}
KINDS = {'mail_draft': 'mail', 'calendar_event': 'calendar', 'document': 'file-write',
         'checklist_task': 'tasks', 'task_status': 'tasks', 'transcription': 'speech'}
SAFE_RETRY = {'search', 'resolve', 'refresh', 'reconcile', 'calendar_event'}


def selected_provider(db, payload, alias):
    for item in integration_context(db, payload)['providers']:
        if item['alias'] == alias and item['configured']:
            return item['selected_provider_app_ids'][0]
    raise ValidationError(f'Select one enabled `{alias}` provider in workspace Settings first.')


def text_field(values, name, *, required=False, limit=10000):
    value = require_text(values, name, required=required)
    if len(value) > limit:
        raise ValidationError(f'`{name}` exceeds {limit} characters.')
    return value


def linked_ref(db, entity, entity_id, ref_id, alias):
    row = db.execute('SELECT * FROM external_refs WHERE id=? AND crm_entity_type=? AND crm_entity_id=? AND deleted_at IS NULL', (ref_id, entity, entity_id)).fetchone()
    if not row or row['provider_alias'] != alias:
        raise ValidationError('Choose a linked record from the required provider.')
    ref = row_to_dict(row)
    if ref['metadata'].get('resolution_status') != 'resolved':
        raise ValidationError('Verify or refresh the linked provider record first.')
    return ref


def build_write(db, payload, operation_id, entity, entity_id):
    kind = require_text(payload, 'kind', required=True)
    if kind not in KINDS:
        raise ValidationError('Unsupported integration operation. Campaigns and direct sending are excluded.')
    args = payload.get('parameters', {})
    if not isinstance(args, dict):
        raise ValidationError('Parameters must be an object.')
    alias = KINDS[kind]
    provider = selected_provider(db, payload, alias)
    body = {}
    if kind == 'mail_draft':
        body = {'action': 'mail_create_draft', 'subject': text_field(args, 'subject', required=True, limit=300),
                'body_text': text_field(args, 'body_text', required=True, limit=50000)}
        if args.get('reply_ref_id'):
            ref = linked_ref(db, entity, entity_id, args['reply_ref_id'], 'mail')
            if ref['source_app_id'] != provider or ref['source_entity_type'] != 'email_thread':
                raise ValidationError('Reply requires a thread from the selected Mail provider.')
            body['thread_id'] = ref['source_entity_id']
        else:
            email = text_field(args, 'to', required=True, limit=320)
            from .website_intake import EMAIL_RE
            if not EMAIL_RE.fullmatch(email):
                raise ValidationError('Enter one valid recipient email address.')
            body['to'] = [{'email': email}]
        if args.get('connection_id'):
            body['connection_id'] = text_field(args, 'connection_id', limit=200)
        attachments = args.get('attachment_ref_ids', [])
        if not isinstance(attachments, list) or len(attachments) > 10:
            raise ValidationError('Choose at most ten linked attachments.')
        for ref_id in attachments:
            ref = linked_ref(db, entity, entity_id, ref_id, 'files')
            if ref['source_app_id'] != selected_provider(db, payload, 'files'):
                raise ValidationError('Attachment provider changed.')
            path = ref['metadata'].get('workspace_relative_path', '')
            if not path.startswith(('storage/uploaded/', 'storage/generated/')) or '..' in PurePosixPath(path).parts:
                raise ValidationError('Mail attachments require local Storage files.')
            body.setdefault('workspace_attachments', []).append(path)
    elif kind == 'calendar_event':
        start, end = (text_field(args, key, required=True, limit=80) for key in ('startTime', 'endTime'))
        try:
            times = [datetime.fromisoformat(t.replace('Z', '+00:00')) for t in (start, end)]
            if any(t.tzinfo is None for t in times) or times[1] <= times[0]:
                raise ValueError()
        except ValueError as error:
            raise ValidationError('Meeting times require ISO timestamps with timezone and end after start.') from error
        attendees = args.get('attendees', [])
        if not isinstance(attendees, list) or len(attendees) > 30 or not all(isinstance(a, str) and '@' in a and len(a) < 320 for a in attendees):
            raise ValidationError('Attendees must be a bounded list of email addresses.')
        body = {'action': 'create', 'title': text_field(args, 'title', required=True, limit=300),
                'description': text_field(args, 'description'), 'startTime': start, 'endTime': end,
                'timezone': text_field(args, 'timezone', limit=80) or 'UTC', 'attendees': attendees,
                'location': text_field(args, 'location', limit=500), 'source': 'crm',
                'external_refs': {'crm': {'entity_type': entity, 'entity_id': entity_id}},
                'idempotency_key': operation_id, 'conflict_policy': 'warn'}
    elif kind == 'document':
        if selected_provider(db, payload, 'files') != provider:
            raise ValidationError('File catalog and file-write must select the same provider.')
        body = {'action': 'write_file', 'workspace_relative_path': f'storage/generated/crm/{operation_id}.md',
                'mode': 'create', 'content': text_field(args, 'content', required=True, limit=50000)}
    elif kind == 'checklist_task':
        ref = linked_ref(db, entity, entity_id, text_field(args, 'ref_id', required=True), 'tasks')
        if ref['source_app_id'] != provider:
            raise ValidationError('Checklist belongs to another provider.')
        section = text_field(args, 'section_id', required=True, limit=200)
        sections = ref['metadata'].get('sections', [])
        if not any(s['id'] == section for s in sections):
            raise ValidationError('Choose an existing section from the refreshed checklist.')
        body = {'action': 'add_task', 'checklist_id': ref['source_entity_id'], 'section_id': section,
                'title': text_field(args, 'title', required=True, limit=300)}
    elif kind == 'task_status':
        ref = linked_ref(db, entity, entity_id, text_field(args, 'ref_id', required=True), 'tasks')
        if ref['source_app_id'] != provider or not ref['metadata'].get('task_id'):
            raise ValidationError('Choose a linked Checklist task from the selected provider.')
        status = text_field(args, 'status', required=True)
        if status not in {'pending', 'in-progress', 'need-help', 'blocked', 'completed', 'failed'}:
            raise ValidationError('Unsupported Checklist task status.')
        body = {'action': 'set_task_status', 'checklist_id': ref['source_entity_id'],
                'section_id': ref['metadata']['section_id'], 'task_id': ref['metadata']['task_id'], 'status': status}
    elif kind == 'transcription':
        ref = linked_ref(db, entity, entity_id, text_field(args, 'ref_id', required=True), 'files')
        if ref['source_app_id'] != selected_provider(db, payload, 'files'):
            raise ValidationError('Audio belongs to another Storage provider.')
        path = ref['metadata'].get('workspace_relative_path', '')
        if not path.startswith(('storage/uploaded/', 'storage/generated/')) or '..' in PurePosixPath(path).parts:
            raise ValidationError('Speech requires a verified local Storage audio file.')
        body = {'action': 'transcribe_file', 'workspace_relative_path': path, 'language': text_field(args, 'language', limit=20)}
    return kind, alias, provider, {'body': body, 'ref_id': args.get('ref_id', '')}
