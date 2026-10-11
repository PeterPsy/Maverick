// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { selectCalendar } from '../../api';
import type { CalendarRemoteCalendar } from '../../components/ui/calendar-types';
import { CalendarSidebar } from './CalendarSidebar';

const fixtures = vi.hoisted(() => ({
  calendar: {
    id: 'primary', connection_id: 'work', provider: 'google', provider_calendar_id: 'ana@example.com',
    summary: 'Work', primary: true, selected: true, access_role: 'owner', sync_enabled: true, availability_enabled: true,
    sync_status: { status: 'ok', last_sync_at: '2026-10-11T17:00:00Z', time_min: '2025-10-11T00:00:00Z', time_max: '2028-10-11T00:00:00Z' },
  },
}));

vi.mock('../../api', () => ({ selectCalendar: vi.fn(), syncCalendar: vi.fn() }));
vi.mock('../../useCalendarPreferences', () => ({ useCalendarPreferences: () => undefined }));
vi.mock('./useCalendarSidebarReads', () => ({ useCalendarSidebarReads: () => {
  const [calendars, setCalendars] = useState<CalendarRemoteCalendar[]>([fixtures.calendar]);
  const [error, setError] = useState('');
  return { events: [], localEventCount: 0, calendars, setCalendars, error, setError, isLoading: false,
    connections: [{ id: 'work', provider: 'google', account_id: 'ana@example.com', account_label: 'Ana', status: 'connected', sync_status: { status: 'ok' } }],
    refreshCalendarState: vi.fn(), scheduleRefresh: vi.fn() };
} }));

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.setItem('maverick.calendar.preferences', JSON.stringify({ locale: 'en-US' }));
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  localStorage.clear();
  vi.clearAllMocks();
});

it('keeps source controls independent and applies the returned settings immediately', async () => {
  await act(async () => root.render(<CalendarSidebar />));
  const inputs = () => Array.from(container.querySelectorAll<HTMLInputElement>('.calendar-source input'));
  vi.mocked(selectCalendar).mockResolvedValueOnce({ ...fixtures.calendar, selected: false });
  await act(async () => inputs()[0].click());
  expect(selectCalendar).toHaveBeenLastCalledWith('calendar', 'work', 'ana@example.com', { selected: false });
  expect(inputs().map((input) => input.checked)).toEqual([false, true, true]);

  vi.mocked(selectCalendar).mockResolvedValueOnce({ ...fixtures.calendar, selected: false, sync_enabled: false });
  await act(async () => inputs()[1].click());
  expect(selectCalendar).toHaveBeenLastCalledWith('calendar', 'work', 'ana@example.com', { syncEnabled: false });
  expect(inputs().map((input) => input.checked)).toEqual([false, false, true]);
  expect(container.querySelector('.calendar-source-meta')?.textContent).toContain('Sync paused');

  vi.mocked(selectCalendar).mockResolvedValueOnce({ ...fixtures.calendar, selected: false, sync_enabled: false, availability_enabled: false });
  await act(async () => inputs()[2].click());
  expect(selectCalendar).toHaveBeenLastCalledWith('calendar', 'work', 'ana@example.com', { availabilityEnabled: false });
  expect(inputs().map((input) => input.checked)).toEqual([false, false, false]);
});

it('shows readable status, labels diagnostic dates and preserves collapsed accounts after updates', async () => {
  await act(async () => root.render(<CalendarSidebar />));
  expect(container.querySelector('.calendar-account-freshness')?.textContent).toBe('Synced');
  expect(container.querySelector('.calendar-source-meta')?.textContent).toBe('Primary calendar');
  const options = container.querySelector('details')!;
  expect(options.open).toBe(false);
  expect(options.textContent).toContain('Downloaded period');
  const toggle = container.querySelector<HTMLButtonElement>('button[aria-expanded]')!;
  act(() => toggle.click());
  expect(toggle.getAttribute('aria-expanded')).toBe('false');
  expect(container.querySelector<HTMLDivElement>('.calendar-account-sources')?.hidden).toBe(true);
  vi.mocked(selectCalendar).mockResolvedValueOnce({ ...fixtures.calendar, selected: false });
  await act(async () => container.querySelector<HTMLInputElement>('.calendar-source input')!.click());
  expect(toggle.getAttribute('aria-expanded')).toBe('false');
});

it('keeps the current setting and displays the failure when saving is rejected', async () => {
  await act(async () => root.render(<CalendarSidebar />));
  vi.mocked(selectCalendar).mockRejectedValueOnce(new Error('Setting rejected'));
  await act(async () => container.querySelector<HTMLInputElement>('.calendar-source input')!.click());
  expect(container.querySelector('[role="alert"]')?.textContent).toBe('Setting rejected');
  expect(container.querySelector<HTMLInputElement>('.calendar-source input')?.checked).toBe(true);
  expect(container.querySelector<HTMLInputElement>('.calendar-source input')?.disabled).toBe(false);
});
