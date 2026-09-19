"""Bounded, live-only operational views over CRM-owned records (no provider I/O)."""
from datetime import datetime, timezone, timedelta

from errors import ValidationError
from store import require_text, row_to_dict

ACTIVE = 'deleted_at IS NULL AND archived_at IS NULL'
SPECS = {
    'tasks': ('tasks', 'task', 'title', 'due_at'),
    'threads': ('conversation_threads', 'conversation_thread', 'title', 'last_activity_at'),
    'expenses': ('expenses', 'expense', 'title', 'incurred_at'),
    'briefs': ('briefs', 'brief', 'title', 'period_start'),
    'intelligence': ('intelligence_profiles', 'intelligence_profile', 'title', 'reviewed_at'),
}


def pagination(payload):
    offset, limit = payload.get('offset', 0), payload.get('limit', 40)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (offset, limit)) or offset < 0 or not 1 <= limit <= 100:
        raise ValidationError('Pagination needs a nonnegative offset and limit from 1 to 100.')
    return offset, limit


def workspace_view(db, payload):
    view = require_text(payload, 'view', required=True)
    if view in {'calendar', 'transcripts', 'quality'}:
        from .workspace_evidence import evidence_view
        return evidence_view(db, payload)
    if view not in SPECS:
        raise ValidationError('Unsupported operational workspace view.')
    table, entity, title, order = SPECS[view]
    offset, limit = pagination(payload)
    query = require_text(payload, 'query')[:300]
    where, params = [ACTIVE], []
    if query:
        where.append(f'lower({title} || \' \' || body) LIKE ?')
        params.append('%' + query.lower() + '%')
    summary = {}
    if view == 'tasks':
        status = require_text(payload, 'status') or 'open'
        if status not in {'open', 'done', 'all'}:
            raise ValidationError('Unsupported task status.')
        if status != 'all':
            where.append('status=?'); params.append(status)
        bucket = require_text(payload, 'bucket') or 'all'
        now = datetime.now(timezone.utc)
        # UI sends its local end-of-day with offset; server default is explicitly UTC.
        anchor = require_text(payload, 'day_end')
        try:
            end = datetime.fromisoformat(anchor.replace('Z', '+00:00')) if anchor else now.replace(hour=23, minute=59, second=59)
            if end.tzinfo is None: raise ValueError()
        except ValueError as error:
            raise ValidationError('day_end must have an ISO timezone.') from error
        bounds = {'today': (None, end), 'week': (end, end + timedelta(days=7)), 'month': (end + timedelta(days=7), end + timedelta(days=30))}
        if bucket in bounds:
            lower, upper = bounds[bucket]
            where.append("due_at != '' AND julianday(due_at) <= julianday(CASE WHEN length(due_at)=10 THEN ? ELSE ? END)")
            params.extend([upper.date().isoformat(), upper.isoformat()])
            if lower:
                where.append('julianday(due_at)>julianday(CASE WHEN length(due_at)=10 THEN ? ELSE ? END)')
                params.extend([lower.date().isoformat(), lower.isoformat()])
        elif bucket == 'unscheduled':
            where.append("due_at=''")
        elif bucket != 'all':
            raise ValidationError('Unsupported task horizon.')
        summary = {str(row['status']): row['total'] for row in db.execute(f'SELECT status,count(*) total FROM tasks WHERE {ACTIVE} GROUP BY status')}
    if view == 'threads':
        bucket = require_text(payload, 'bucket') or 'all'
        predicates = {'reply': "status NOT IN ('waiting','completed','closed','dismissed')", 'waiting': "status='waiting'", 'completed': "status IN ('completed','closed','dismissed')"}
        if bucket in predicates: where.append(predicates[bucket])
        elif bucket != 'all': raise ValidationError('Unsupported thread state.')
        summary = {name: db.execute(f'SELECT count(*) FROM conversation_threads WHERE {ACTIVE} AND {clause}').fetchone()[0] for name, clause in predicates.items()}
    if view == 'expenses':
        summary['currencies'] = [dict(row) for row in db.execute(f'SELECT currency,sum(amount_minor) amount_minor,count(*) total FROM expenses WHERE {" AND ".join(where)} GROUP BY currency', params)]
    total = db.execute(f'SELECT count(*) FROM {table} WHERE {" AND ".join(where)}', params).fetchone()[0]
    direction = 'ASC' if view == 'tasks' else 'DESC'
    rows = db.execute(f'SELECT * FROM {table} WHERE {" AND ".join(where)} ORDER BY {order} {direction}, id LIMIT ? OFFSET ?', [*params, limit, offset]).fetchall()
    items = [{**row_to_dict(row), 'entity_type': entity} for row in rows]
    return {'ok': True, 'items': items, 'total': total, 'has_more': offset + len(items) < total, 'offset': offset, 'summary': summary}
