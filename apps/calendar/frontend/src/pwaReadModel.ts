import { displayFields, displayList, displayRecord, displayStrings } from '@maverick/pwa-cache';
import type { CalendarEventPayload, CalendarRemoteCalendarPayload } from './types';

export type CalendarReadModel = { events: CalendarEventPayload[]; calendars: CalendarRemoteCalendarPayload[]; has_more: boolean };
export function sanitizeCalendarReadModel(value: unknown): CalendarReadModel | null {
  const model = displayRecord(value);
  if (!model || typeof model.has_more !== 'boolean') return null;
  const events = displayList(model.events, (item) => {
    const raw = displayRecord(item);
    const event = displayFields(item, {
      text: ['id', 'title', 'description', 'startTime', 'endTime', 'status', 'timezone', 'location', 'organizer', 'color', 'category', 'created_at', 'updated_at', 'source'],
      number: ['revision'], boolean: ['all_day'],
    });
    if (!raw || !event || !event.id || typeof event.title !== 'string' || typeof event.color !== 'string'
      || !Number.isFinite(Date.parse(String(event.startTime))) || !Number.isFinite(Date.parse(String(event.endTime)))) return null;
    for (const field of ['attendees', 'tags']) {
      const list = displayStrings(raw[field] ?? []);
      if (!list) return null;
      event[field] = list;
    }
    const refs = displayFields(raw.external_refs ?? {}, { text: ['provider', 'calendar_connection_id', 'calendar_id', 'provider_calendar_id', 'account_id'] });
    if (!refs) return null;
    event.external_refs = refs;
    return event as unknown as CalendarEventPayload;
  });
  const calendars = displayList(model.calendars, (item) => {
    const calendar = displayFields(item, { text: ['id', 'connection_id', 'provider', 'provider_calendar_id', 'summary', 'description', 'timezone', 'color', 'updated_at'], boolean: ['primary', 'selected'] });
    return calendar && ['id', 'connection_id', 'provider', 'provider_calendar_id'].every((key) => typeof calendar[key] === 'string')
      ? calendar as unknown as CalendarRemoteCalendarPayload : null;
  });
  return events && calendars ? { events, calendars, has_more: model.has_more } : null;
}
