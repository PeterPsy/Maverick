// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { CalendarEventOverlay } from './calendar-event-overlay';
import { notifyCalendarUiStateChanged, readCalendarUiState, writeCalendarUiState } from '@/calendar-ui-state';
import type { Event } from './calendar-types';
vi.mock('@/api', () => ({ CalendarApiError: class extends Error {}, getFullEvent: vi.fn(async () => null) }));
vi.mock('./find-time', () => ({ FindTime: () => null }));
vi.mock('./calendar-event-panel', () => ({ EventPanel: (props: { draft: Event; setDraft: (patch: Partial<Event>) => void; onCreate: () => void; onClose: () => void }) => <div><span>{props.draft?.title} {props.draft?.location} {String(props.draft?.recurrence?.count || "")}</span><button onClick={() => props.setDraft({ title: 'My draft' })}>Edit</button><button onClick={props.onCreate}>Save</button><button onClick={props.onClose}>Close</button></div> }));
afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });
const event: Event = { id: 'e', title: 'Original', startTime: new Date('2026-10-04T09:00Z'), endTime: new Date('2026-10-04T10:00Z'), color: 'blue', revision: 1 };
it('preserves dirty drafts across refresh and prevents accidental closing', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  writeCalendarUiState('calendar', { sidebarMode: 'details', selectedEventId: 'e' });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const props = { runtimeAppId: 'calendar', events: [event], connections: [], calendars: [], categories: [], availableTags: [], onCreateEvent: vi.fn(), onUpdateEvent: vi.fn(), onDeleteEvent: vi.fn() };
  try {
    await act(async () => root.render(<CalendarEventOverlay {...props} />));
    act(() => host.querySelector<HTMLButtonElement>('button')!.click());
    await act(async () => root.render(<CalendarEventOverlay {...props} events={[{ ...event, title: 'Changed elsewhere', revision: 2 }]} />));
    expect(host.textContent).toContain('My draft'); expect(host.textContent).not.toContain('Changed elsewhere');
    window.confirm = vi.fn(() => false);
    act(() => host.querySelectorAll<HTMLButtonElement>('button')[2].click());
    expect(host.querySelector('[role=dialog]')).not.toBeNull();
  } finally { act(() => root.unmount()); host.remove(); }
});
it('retries a lost create response with the same idempotency key and contextual time', async () => {
  writeCalendarUiState('calendar', { sidebarMode: 'create', selectedEventId: '', createStart: '2026-10-04T09:15:00Z', requestId: 'create-request' });
  const host = document.createElement('div'); const root = createRoot(host);
  const create = vi.fn().mockRejectedValueOnce(new Error('Response lost')).mockResolvedValueOnce(event);
  const props = { runtimeAppId: 'calendar', events: [], connections: [], calendars: [], categories: [], availableTags: [], onCreateEvent: create, onUpdateEvent: vi.fn(), onDeleteEvent: vi.fn() };
  try {
    await act(async () => root.render(<CalendarEventOverlay {...props} />));
    act(() => host.querySelector<HTMLButtonElement>('button')!.click());
    await act(async () => host.querySelectorAll<HTMLButtonElement>('button')[1].click());
    await act(async () => { notifyCalendarUiStateChanged('calendar'); root.render(<CalendarEventOverlay {...props} categories={['Meeting']} />); });
    await act(async () => host.querySelectorAll<HTMLButtonElement>('button')[1].click());
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[0][0].idempotency_key).toBe(create.mock.calls[1][0].idempotency_key);
    expect(create.mock.calls[0][0].startTime.toISOString()).toBe('2026-10-04T09:15:00.000Z');
    expect(host.querySelector('[role=dialog]')).toBeNull();
    expect(readCalendarUiState('calendar').sidebarMode).toBe('idle');
    await act(async () => { notifyCalendarUiStateChanged('calendar'); });
    expect(host.querySelector('[role=dialog]')).toBeNull();
  } finally { act(() => root.unmount()); }
});
it('keeps full event details when a display refresh has the same revision', async () => {
  const { getFullEvent } = await import('@/api');
  vi.mocked(getFullEvent).mockResolvedValueOnce({ ...event, location: 'Room 1', recurrence: { frequency: 'weekly', count: 3 } });
  writeCalendarUiState('calendar', { sidebarMode: 'details', selectedEventId: 'e' });
  const host = document.createElement('div'); const root = createRoot(host);
  const update = vi.fn().mockResolvedValue(event);
  const props = { runtimeAppId: 'calendar', events: [event], connections: [], calendars: [], categories: [], availableTags: [], onCreateEvent: vi.fn(), onUpdateEvent: update, onDeleteEvent: vi.fn() };
  try {
    await act(async () => root.render(<CalendarEventOverlay {...props} />));
    await act(async () => root.render(<CalendarEventOverlay {...props} events={[{ ...event }]} categories={['Meeting']} />));
    act(() => host.querySelector<HTMLButtonElement>('button')!.click());
    vi.mocked(getFullEvent).mockClear();
    expect(host.textContent).toContain('My draft Room 1 3');
    expect(getFullEvent).not.toHaveBeenCalled();
  } finally { act(() => root.unmount()); }
});
it('merges untouched full metadata into a draft edited while details are loading', async () => {
  const { getFullEvent } = await import('@/api');
  let resolveDetails!: (event: Event) => void;
  vi.mocked(getFullEvent).mockReturnValueOnce(new Promise<Event>(resolve => { resolveDetails = resolve; }));
  writeCalendarUiState('calendar', { sidebarMode: 'details', selectedEventId: 'e' });
  const host = document.createElement('div'); const root = createRoot(host);
  const props = { runtimeAppId: 'calendar', events: [event], connections: [], calendars: [], categories: [], availableTags: [], onCreateEvent: vi.fn(), onUpdateEvent: vi.fn(), onDeleteEvent: vi.fn() };
  try {
    await act(async () => root.render(<CalendarEventOverlay {...props} />));
    act(() => host.querySelector<HTMLButtonElement>('button')!.click());
    await act(async () => resolveDetails({ ...event, location: 'Room 2', recurrence: { frequency: 'weekly', count: 4 } }));
    expect(host.textContent).toContain('My draft Room 2 4');
  } finally { act(() => root.unmount()); }
});
