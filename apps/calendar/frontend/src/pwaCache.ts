import { readAppCacheModel, readAppCachePages } from '@maverick/pwa-cache';
import { sanitizeCalendarReadModel, type CalendarReadModel } from './pwaReadModel';
import type { CalendarEvent } from './types';

export function calendarWindow(date: Date): { start_after: string; end_before: string } {
  return {
    start_after: new Date(Date.UTC(date.getFullYear(), date.getMonth(), -6)).toISOString(),
    end_before: new Date(Date.UTC(date.getFullYear(), date.getMonth() + 1, 8)).toISOString(),
  };
}
export function calendarEvents(model: CalendarReadModel): CalendarEvent[] {
  return model.events.map((event) => ({ ...event, startTime: new Date(event.startTime), endTime: new Date(event.endTime) }));
}
export async function readCalendarWindow(
  interval: ReturnType<typeof calendarWindow>, signal: AbortSignal,
  onUpdate: (model: CalendarReadModel) => void,
  onRevalidationError: (error: unknown) => void,
): Promise<void> {
  await readAppCachePages<CalendarReadModel>({
    signal, pageSize: 500, hasMore: (page) => page.has_more, onError: onRevalidationError,
    onUpdate: (pages) => onUpdate({ events: pages.flatMap((page) => page.events), calendars: pages[0]?.calendars ?? [], has_more: pages.at(-1)?.has_more ?? false }),
    readPage: async (offset, onRevalidated) => (await readAppCacheModel({
      appId: 'calendar', resource: 'bounded-event-window', schemaRevision: 'calendar.bounded-event-window.v1',
      parameters: { kind: 'window', ...interval, offset },
    }, sanitizeCalendarReadModel, { signal, onRevalidated, onRevalidationError })).payload,
  });
}

export async function readCalendarEvent(eventId: string, signal: AbortSignal, onUpdate: (event: CalendarEvent) => void, onError: (error: unknown) => void): Promise<void> {
  const publish = (model: CalendarReadModel) => {
    if (!signal.aborted && model.events.length === 1 && model.events[0].id === eventId) onUpdate(calendarEvents(model)[0]);
  };
  const result = await readAppCacheModel({
    appId: 'calendar', resource: 'bounded-event-window', schemaRevision: 'calendar.bounded-event-window.v1',
    parameters: { kind: 'event', event_id: eventId },
  }, sanitizeCalendarReadModel, { signal, onRevalidated: publish, onRevalidationError: onError });
  publish(result.payload);
}
