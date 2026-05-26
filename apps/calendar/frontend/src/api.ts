import type { CalendarActionResult, CalendarEvent, CalendarEventPayload, CalendarViewState } from './types';

async function request(appId: string, body: Record<string, unknown>): Promise<CalendarActionResult> {
  const response = await fetch(`/api/apps/${encodeURIComponent(appId)}/backend`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const data = (await response.json()) as CalendarActionResult;
  if (!response.ok || data.error) {
    throw new Error(data.detail || data.error || 'Calendar request failed.');
  }
  return data;
}

export async function listEvents(appId: string): Promise<CalendarEvent[]> {
  const data = await request(appId, { action: 'list' });
  return (data.events || []).map(fromPayload);
}

export async function readViewFilter(appId: string): Promise<CalendarViewState> {
  const data = await request(appId, { action: 'view_filter' });
  return data.view_state || {};
}

export async function createEvent(
  appId: string,
  event: Omit<CalendarEvent, 'id'> & { id?: string },
): Promise<CalendarEvent> {
  const data = await request(appId, { action: 'create', event: toPayload(event, { includeId: false, includeIdempotencyKey: true }) });
  if (!data.event) {
    throw new Error('Calendar event was not created.');
  }
  return fromPayload(data.event);
}

export async function updateEvent(appId: string, id: string, event: Partial<CalendarEvent>): Promise<CalendarEvent> {
  const body: Record<string, unknown> = { action: 'update', id, event: toPayload(event) };
  if (event.revision !== undefined) {
    body.expected_revision = event.revision;
  }
  const data = await request(appId, body);
  if (!data.event) {
    throw new Error('Calendar event was not saved.');
  }
  return fromPayload(data.event);
}

export async function deleteEvent(appId: string, id: string, expectedRevision?: number): Promise<void> {
  const body: Record<string, unknown> = { action: 'delete', id };
  if (expectedRevision !== undefined) {
    body.expected_revision = expectedRevision;
  }
  await request(appId, body);
}

function fromPayload(event: CalendarEventPayload): CalendarEvent {
  return {
    ...event,
    startTime: new Date(event.startTime),
    endTime: new Date(event.endTime),
    timezone: event.timezone || 'UTC',
    all_day: event.all_day || false,
    attendees: event.attendees || [],
    tags: event.tags || [],
    external_refs: event.external_refs || {},
    recurrence: event.recurrence || {},
    reminders: event.reminders || []
  };
}

function toPayload(
  event: Partial<CalendarEvent>,
  options: { includeId?: boolean; includeIdempotencyKey?: boolean } = {},
): Partial<CalendarEventPayload> {
  const payload: Partial<CalendarEventPayload> = {};
  if (options.includeId !== false && event.id !== undefined) payload.id = event.id;
  if (event.title !== undefined) payload.title = event.title;
  if (event.description !== undefined) payload.description = event.description;
  if (event.startTime !== undefined) payload.startTime = event.startTime.toISOString();
  if (event.endTime !== undefined) payload.endTime = event.endTime.toISOString();
  if (event.status !== undefined) payload.status = event.status;
  if (event.timezone !== undefined) payload.timezone = event.timezone;
  if (event.location !== undefined) payload.location = event.location;
  if (event.organizer !== undefined) payload.organizer = event.organizer;
  if (event.all_day !== undefined) payload.all_day = event.all_day;
  if (event.color !== undefined) payload.color = event.color;
  if (event.category !== undefined) payload.category = event.category;
  if (event.attendees !== undefined) payload.attendees = event.attendees;
  if (event.tags !== undefined) payload.tags = event.tags;
  if (event.source !== undefined) payload.source = event.source;
  if (event.external_refs !== undefined) payload.external_refs = event.external_refs;
  if (event.recurrence !== undefined) payload.recurrence = event.recurrence;
  if (event.reminders !== undefined) payload.reminders = event.reminders;
  if (options.includeIdempotencyKey && event.idempotency_key !== undefined) payload.idempotency_key = event.idempotency_key;
  return payload;
}
