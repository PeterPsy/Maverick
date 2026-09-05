import { describe, expect, it, vi } from 'vitest';
import { calendarWindow } from './pwaCache';
import { sanitizeCalendarReadModel } from './pwaReadModel';

vi.mock('@maverick/pwa-cache', async (original) => ({ ...await original<object>(), readAppCacheModel: vi.fn() }));

describe('Calendar persistent display model', () => {
  const event = { id: 'e', title: 'Event', startTime: '2026-09-05T10:00:00Z', endTime: '2026-09-05T11:00:00Z', color: 'blue' };
  it('projects only event and calendar display fields', () => {
    const result = sanitizeCalendarReadModel({ events: [{ ...event, token: 'secret', external_refs: { provider: 'google', calendar_connection_id: 'c', access_token: 'secret' } }], calendars: [], has_more: false, authority: 'secret' });
    expect(result?.events[0]).toMatchObject(event);
    expect(JSON.stringify(result)).not.toMatch(/secret|authority|token/);
  });
  it('rejects malformed dates and list members instead of silently dropping them', () => {
    expect(sanitizeCalendarReadModel({ events: [{ ...event, startTime: 'bad' }], calendars: [], has_more: false })).toBeNull();
    expect(sanitizeCalendarReadModel({ events: [event, null], calendars: [], has_more: false })).toBeNull();
  });
  it('bounds the visible month including adjacent grid days', () => {
    const window = calendarWindow(new Date(2026, 8, 15));
    expect(Date.parse(window.end_before) - Date.parse(window.start_after)).toBeLessThan(93 * 86400000);
    expect(window.start_after).toBe('2026-08-25T00:00:00.000Z');
  });
  it('publishes warm pages and changed revalidation without waiting for other reads', async () => {
    const { readAppCacheModel } = await import('@maverick/pwa-cache');
    const { readCalendarWindow } = await import('./pwaCache');
    const initial = { events: [event], calendars: [], has_more: false };
    vi.mocked(readAppCacheModel).mockResolvedValue({ payload: initial } as never);
    const update = vi.fn();
    await readCalendarWindow(calendarWindow(new Date()), new AbortController().signal, update, vi.fn());
    expect(update).toHaveBeenCalledWith(initial);
    const options = vi.mocked(readAppCacheModel).mock.calls.at(-1)![2]!;
    options.onRevalidated?.({ ...initial, events: [{ ...event, title: 'Changed' }] });
    expect(update.mock.calls.at(-1)![0].events[0].title).toBe('Changed');
  });
});
