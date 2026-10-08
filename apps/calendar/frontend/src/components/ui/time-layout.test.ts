// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { movedEventTimes, navigateMonth, parseZonedInput, timelineEvents, zonedInput } from './time-layout';
import { eventsForDate } from './calendar-utils';
import type { Event } from './calendar-types';
const event = (patch: Partial<Event> = {}): Event => ({ id: 'one', title: 'Meeting', color: 'blue', startTime: new Date(2026, 0, 31, 9, 30), endTime: new Date(2026, 0, 31, 11), ...patch });
describe('calendar date and layout regressions', () => {
  it('keeps the selected day across short months', () => {
    const feb = navigateMonth(new Date(2026, 0, 31), 1, 31);
    expect([feb.getMonth(), feb.getDate()]).toEqual([1, 28]);
    expect(navigateMonth(feb, 1, 31).getDate()).toBe(31);
  });
  it('preserves time for month drops and uses quarter-hour slots', () => {
    const day = new Date(2026, 1, 4);
    expect(movedEventTimes(event(), day).startTime.getMinutes()).toBe(30);
    expect(movedEventTimes(event(), day).startTime.getHours()).toBe(9);
    expect(movedEventTimes(event(), day, 10.25).startTime.getMinutes()).toBe(15);
  });
  it('renders one duration block and assigns overlap columns', () => {
    const rows = timelineEvents([event(), event({ id: 'two', startTime: new Date(2026, 0, 31, 10), endTime: new Date(2026, 0, 31, 12) }), event({ id: 'all', all_day: true })], new Date(2026, 0, 31));
    expect(rows).toHaveLength(2); expect(rows[0]).toMatchObject({ start: 570, end: 660, column: 0, columns: 2 });
    expect(rows[1].column).toBe(1);
  });
  it('roundtrips civil dates and preserves all-day lengths across DST drops', () => {
    const original = event({ all_day: true, timezone: 'Europe/Rome', startTime: parseZonedInput('2026-03-28', 'Europe/Rome'), endTime: parseZonedInput('2026-03-29', 'Europe/Rome') });
    const moved = movedEventTimes(original, new Date(2026, 2, 29));
    expect(zonedInput(moved.startTime, 'Europe/Rome', true)).toBe('2026-03-29');
    expect(zonedInput(moved.endTime, 'Europe/Rome', true)).toBe('2026-03-30');
    expect(moved.endTime.getTime() - moved.startTime.getTime()).toBe(23 * 3600000);
    expect(Number.isNaN(parseZonedInput('2026-03-29T02:30', 'Europe/Rome').getTime())).toBe(true);
  });
  it('shows all-day events only on their civil dates', () => {
    const allDay = event({ all_day: true, all_day_start: '2026-10-04', all_day_end: '2026-10-05', startTime: new Date('2026-10-03T22:00Z'), endTime: new Date('2026-10-04T22:00Z') });
    expect(eventsForDate([allDay], new Date(2026, 9, 3))).toHaveLength(0);
    expect(eventsForDate([allDay], new Date(2026, 9, 4))).toHaveLength(1);
  });
});
