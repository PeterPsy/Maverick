"""Approved CRM customer display reads; workflow/action authority stays live."""
import json
from pathlib import Path

from core.app_sdk.display_models import conditional_display_response, project_display_model
from domains.bootstrap import bootstrap_payload
from domains.custom_fields import schema_config
from domains.pipeline import pipeline_board
from domains.record_queries import search
from domains.records import records_table
from errors import ValidationError
from store import get_record

SCHEMAS = json.loads((Path(__file__).resolve().parents[1] / 'pwa_read_models.v1.json').read_text())


def read_model(db, data_root, body):
    kind = body.get('kind')
    if kind not in SCHEMAS:
        raise ValidationError('Unsupported CRM display read.')
    if kind == 'bootstrap':
        source = bootstrap_payload(db, data_root)
    elif kind == 'schema':
        source = schema_config(db)
    elif kind == 'records_table':
        source = records_table(db, {
            'entity_type': body.get('entity_type', 'all'), 'query': body.get('query', ''), 'filters': body.get('filters', {}),
            'sort': {'field': body.get('sort_field', 'updated_at'), 'direction': body.get('sort_direction', 'desc')},
            'pagination': {'cursor': body.get('cursor', ''), 'limit': body.get('limit', 50)},
        })
    elif kind == 'pipeline_board':
        source = pipeline_board(db, {'pipeline_id': body.get('pipeline_id', '')})
    elif kind == 'get':
        source = {'record': get_record(db, str(body.get('entity_type') or ''), str(body.get('id') or ''))}
    else:
        source = search(db, {'query': body.get('query', ''), 'entity_type': body.get('entity_type', 'all'), 'limit': min(100, max(1, int(body.get('limit', 50))))})
    try:
        payload = {'kind': kind, 'data': project_display_model(source, SCHEMAS[kind])}
        return conditional_display_response(payload, body.get('known_revision'))
    except ValueError as error:
        raise ValidationError(str(error)) from error
