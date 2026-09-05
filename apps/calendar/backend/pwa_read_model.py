"""Bounded Calendar display projection. No connection, OAuth or write authority."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

from google_calendars import list_calendars
from operations import get_event, list_events

EVENT_FIELDS = ('id', 'title', 'description', 'startTime', 'endTime', 'status', 'timezone', 'location', 'organizer', 'color', 'category', 'created_at', 'updated_at', 'source', 'revision', 'all_day', 'attendees', 'tags')
CALENDAR_FIELDS = ('id', 'connection_id', 'provider', 'provider_calendar_id', 'summary', 'description', 'timezone', 'color', 'updated_at', 'primary', 'selected')
REF_FIELDS = ('provider', 'calendar_connection_id', 'calendar_id', 'provider_calendar_id', 'account_id')


def read_model(data_root: Path, body: dict) -> dict:
    if body.get('kind') == 'event':
        event = get_event(data_root, str(body.get('event_id') or ''))
        if event is None:
            raise ValueError('Calendar event was not found.')
        events = [event]
        has_more = False
    elif body.get('kind') == 'window':
        start = datetime.fromisoformat(str(body.get('start_after') or '').replace('Z', '+00:00'))
        end = datetime.fromisoformat(str(body.get('end_before') or '').replace('Z', '+00:00'))
        if not start.tzinfo or not end.tzinfo or not 0 < (end - start).total_seconds() <= 93 * 86400:
            raise ValueError('Calendar cache windows require a bounded timezone-aware interval.')
        offset = body.get('offset', 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > 100000:
            raise ValueError('Invalid event page offset.')
        page = list_events(data_root, start_after=start.isoformat(), end_before=end.isoformat(), limit=501, offset=offset)
        events, has_more = page[:500], len(page) > 500
    else:
        raise ValueError('Unsupported Calendar display read.')
    projected = []
    for event in events:
        item = {key: event[key] for key in EVENT_FIELDS if key in event}
        item['external_refs'] = {key: event.get('external_refs', {})[key] for key in REF_FIELDS if key in event.get('external_refs', {})}
        projected.append(item)
    payload = {
        'events': projected, 'has_more': has_more,
        'calendars': [{key: row[key] for key in CALENDAR_FIELDS if key in row} for row in list_calendars(data_root, {}).get('calendars', [])],
    }
    revision = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return {'revision': revision, 'not_modified': True} if body.get('known_revision') == revision else {'revision': revision, 'payload': payload}
