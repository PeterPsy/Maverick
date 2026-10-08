// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { DayView, MonthView } from './calendar-views';
import type { Event } from './calendar-types';
const day = new Date(2026, 9, 4);
const meeting: Event = { id: 'meeting', title: 'Meeting', color: 'blue', startTime: new Date(2026, 9, 4, 9, 30), endTime: new Date(2026, 9, 4, 11) };
const props = { currentDate: day, events: [meeting], getColorClasses: () => ({ name: 'Blue', value: 'blue', bg: 'bg-blue', text: 'text-blue', border: 'border-blue' }), onEventClick: vi.fn(), onDragStart: vi.fn(), onDragEnd: vi.fn(), onDrop: vi.fn(), onCreateAt: vi.fn(), onDayOpen: vi.fn() };
it('renders one timed block, separates all-day events and opens events with the keyboard', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const onEventClick = vi.fn();
  try {
    await act(async () => root.render(<DayView {...props} onEventClick={onEventClick} events={[meeting, { ...meeting, id: 'all-day', all_day: true, all_day_start: '2026-10-04', all_day_end: '2026-10-05' }]} />));
    expect(host.querySelectorAll('.calendar-timed-event')).toHaveLength(1);
    expect(host.querySelectorAll('.calendar-all-day [role="button"]')).toHaveLength(1);
    const event = host.querySelector<HTMLElement>('.calendar-timed-event [role="button"]')!;
    act(() => event.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(onEventClick).toHaveBeenCalledWith(meeting);
    const quarters = host.querySelectorAll<HTMLButtonElement>('.calendar-quarter');
    act(() => quarters[37].click());
    expect(props.onCreateAt).toHaveBeenCalledWith(day, 9.25);
  } finally { act(() => root.unmount()); host.remove(); }
});
it('opens the full day from month overflow and creates on the selected civil day', async () => {
  const host = document.createElement('div'); const root = createRoot(host);
  const onDayOpen = vi.fn(), onCreateAt = vi.fn();
  try {
    await act(async () => root.render(<MonthView {...props} onDayOpen={onDayOpen} onCreateAt={onCreateAt} events={Array.from({ length: 4 }, (_, i) => ({ ...meeting, id: `event-${i}` }))} />));
    const overflow = Array.from(host.querySelectorAll<HTMLButtonElement>('button')).find(b => b.textContent?.startsWith('+1'))!;
    act(() => overflow.click());
    expect(onDayOpen.mock.calls[0][0].toDateString()).toBe(day.toDateString());
    const create = Array.from(host.querySelectorAll<HTMLButtonElement>('button')).find(b => b.textContent === '4')!;
    act(() => create.click());
    expect(onCreateAt.mock.calls[0][0].toDateString()).toBe(day.toDateString());
  } finally { act(() => root.unmount()); }
});
