"""Read-only app evidence and data-quality queues, with explicit provenance."""
import json

from entity_catalog import ENTITY_TABLES
from errors import ValidationError
from store import require_text, row_to_dict
from .workspace_views import ACTIVE, pagination


def active_reference_targets():
    # Closed catalog: never interpolate caller-supplied identifiers.
    return ' OR '.join(f"(r.crm_entity_type='{entity}' AND EXISTS(SELECT 1 FROM {table} t WHERE t.id=r.crm_entity_id AND t.deleted_at IS NULL AND t.archived_at IS NULL))" for entity, table in ENTITY_TABLES.items())


def evidence_view(db, payload):
    view = payload['view']
    offset, limit = pagination(payload)
    query = require_text(payload, 'query')[:300].lower()
    if view == 'quality':
        entity = require_text(payload, 'entity_type') or 'contact'
        if entity not in {'contact', 'account', 'lead'}:
            raise ValidationError('Quality review supports people, companies and leads.')
        table = ENTITY_TABLES[entity]
        field = 'domain' if entity == 'account' else 'email'
        title = 'display_name' if entity == 'contact' else 'name'
        if entity == 'lead': title = 'display_name'
        where = f"{ACTIVE} AND trim({field})='' AND lower({title}) LIKE ?"
        args = ['%' + query + '%']
        total = db.execute(f'SELECT count(*) FROM {table} WHERE {where}', args).fetchone()[0]
        rows = db.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY updated_at DESC,id LIMIT ? OFFSET ?', [*args, limit, offset]).fetchall()
        items = [{**row_to_dict(row), 'entity_type': entity, 'quality_issue': 'missing_' + field} for row in rows]
    elif view == 'calendar':
        where = f"r.deleted_at IS NULL AND r.provider_alias='calendar' AND r.source_entity_type='event' AND ({active_reference_targets()}) AND lower(r.title || ' ' || r.summary) LIKE ?"
        args = ['%' + query + '%']
        # Filter before pagination; dates without a timezone are rejected.
        from datetime import datetime
        for key, operator in (('from', '>='), ('until', '<')):
            value = require_text(payload, key)
            if value:
                try:
                    if datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
                        raise ValueError()
                except ValueError as error:
                    raise ValidationError('Calendar bounds must have an ISO timezone.') from error
                where += f" AND julianday(coalesce(nullif(json_extract(r.metadata_json,'$.startTime'),''),r.occurred_at)) {operator} julianday(?)"
                args.append(value)
        # One CRM link per row preserves all CRM contexts.
        total = db.execute(f'SELECT count(*) FROM external_refs r WHERE {where}', args).fetchone()[0]
        rows = db.execute(f"SELECT r.* FROM external_refs r WHERE {where} ORDER BY coalesce(json_extract(r.metadata_json,'$.startTime'), r.occurred_at), r.id LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        items = [row_to_dict(row) for row in rows]
    else:
        where = "i.kind='transcription' AND lower(i.request_json || ' ' || i.result_json) LIKE ? AND (" + ' OR '.join(f"(i.entity_type='{entity}' AND EXISTS(SELECT 1 FROM {table} t WHERE t.id=i.entity_id AND t.deleted_at IS NULL AND t.archived_at IS NULL))" for entity, table in ENTITY_TABLES.items()) + ')'
        args = ['%' + query + '%']
        total = db.execute(f'SELECT count(*) FROM integration_operations i WHERE {where}', args).fetchone()[0]
        rows = db.execute(f'SELECT i.* FROM integration_operations i WHERE {where} ORDER BY i.created_at DESC,i.id LIMIT ? OFFSET ?', [*args, limit, offset]).fetchall()
        items = []
        for row in rows:
            result = json.loads(row['result_json'])
            proposal = db.execute('SELECT * FROM workflow_proposals WHERE id=?', (result.get('review_proposal_id', ''),)).fetchone()
            items.append({'id': row['id'], 'entity_type': row['entity_type'], 'entity_id': row['entity_id'],
                          'provider_app_id': row['provider_app_id'], 'status': row['status'], 'created_at': row['created_at'],
                          'text': result.get('text', ''), 'last_error': row['last_error'],
                          'review_proposal': row_to_dict(proposal) if proposal else None})
    return {'ok': True, 'items': items, 'total': total, 'has_more': offset + len(items) < total, 'offset': offset, 'summary': {}}
