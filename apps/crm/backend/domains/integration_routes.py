"""Small router for the explicitly declared CRM integration surface."""
from errors import ValidationError
from store import require_text
from . import integration_operations as ops
from .integration_callbacks import complete
from .integration_sync import refresh
from .meeting_workflows import meeting_brief, record_outcome

ACTIONS = {'integration_prepare', 'integration_run', 'integration_retry', 'integration_search',
           'integration_link', 'integration_reconcile', 'integration_get', 'integration_list',
           'integration_refresh', 'integration_callback', 'integration_tick', 'meeting_brief', 'meeting_outcome'}


def route(db, action, payload):
    action = action.removeprefix('crm.')
    if action == 'integration_prepare':
        return ops.prepare(db, payload)
    if action in {'integration_run', 'integration_retry'}:
        return ops.dispatch(db, payload, retry=action == 'integration_retry')
    if action in {'integration_search', 'integration_link', 'integration_reconcile'}:
        return ops.read_request(db, payload, kind={'integration_search': 'search', 'integration_link': 'resolve', 'integration_reconcile': 'reconcile'}[action])
    if action == 'integration_get':
        return {'ok': True, 'operation': ops.operation(db, require_text(payload, 'id', required=True))}
    if action == 'integration_list':
        return ops.list_operations(db, payload)
    if action == 'integration_callback':
        return complete(db, payload)
    if action in {'integration_refresh', 'integration_tick'}:
        if action == 'integration_tick' and payload.get('_trusted_surface') != 'background_tick':
            raise ValidationError('Only the core background hook can tick integrations.')
        return refresh(db, payload, background=action == 'integration_tick')
    if action == 'meeting_brief':
        return meeting_brief(db, payload)
    return record_outcome(db, payload)
