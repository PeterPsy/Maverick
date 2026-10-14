// @vitest-environment happy-dom
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, expect, it } from 'vitest';
import { SyncDetails, SyncSummary, syncPresentation } from './sync-status';

afterEach(() => localStorage.clear());

function english() {
  localStorage.setItem('loopino.calendar.preferences', JSON.stringify({ locale: 'en-US' }));
}

it('turns provider statuses into readable labels without hiding incomplete or failed syncs', () => {
  english();
  expect(syncPresentation({ status: 'ok' }).label).toBe('Synced');
  expect(syncPresentation({ status: 'ok', has_more: true }).label).toBe('Partial sync');
  expect(syncPresentation({ status: 'partial', last_sync_at: '2026-10-11T17:00:00Z', stale: true }).label).toBe('Partial sync');
  expect(syncPresentation({ status: 'ok', error: 'Quota exceeded' }, undefined, false, false).label).toBe('Sync failed');
  expect(syncPresentation({ status: 'ok' }, undefined, false, false).label).toBe('Sync paused');
  expect(syncPresentation({ status: 'ok' }, undefined, false, true, 'error').label).toBe('Account needs attention');
  expect(syncPresentation({ status: 'ok' }, undefined, true).label).toBe('Syncing');
  expect(syncPresentation({ status: 'idle', stale: true }).label).toBe('Never synced');
  expect(syncPresentation({ status: 'ok', stale: true, last_sync_at: '2026-10-10T17:00:00Z' }).label).toBe('Data needs updating');
});

it('uses the Calendar language and safely handles absent or invalid dates', () => {
  localStorage.setItem('loopino.calendar.preferences', JSON.stringify({ locale: 'it-IT' }));
  const markup = renderToStaticMarkup(<SyncSummary status={{ status: 'ok', last_sync_at: 'not-a-date' }} showTime />);
  expect(markup).toContain('Sincronizzato');
  expect(markup).not.toContain('Invalid Date');
  expect(markup).not.toContain('<time');
  const details = renderToStaticMarkup(<SyncDetails status={{ time_min: 'invalid', time_max: '2028-10-11T00:00:00Z' }} />);
  expect(details).toContain('Periodo scaricato');
  expect(details).toContain('Nessuna data iniziale');
  expect(details).toContain('Mai sincronizzato');
});
