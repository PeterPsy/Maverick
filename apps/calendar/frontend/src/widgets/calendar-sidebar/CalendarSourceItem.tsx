import { ChevronRight, Settings2 } from 'lucide-react';
import type { CalendarRemoteCalendar } from '../../components/ui/calendar-types';
import { t } from '../../preferences';
import type { CalendarOptions } from './CalendarSidebar';
import { SyncDetails, SyncSummary, syncPresentation } from './sync-status';

export function CalendarSourceItem({ calendar, busy, onUpdate }: {
  calendar: CalendarRemoteCalendar;
  busy: boolean;
  onUpdate: (calendar: CalendarRemoteCalendar, options: CalendarOptions) => Promise<void>;
}) {
  const name = calendar.summary || calendar.provider_calendar_id;
  const readOnly = !['owner', 'writer'].includes(calendar.access_role || '');
  const sync = syncPresentation(calendar.sync_status, undefined, false, calendar.sync_enabled !== false);
  const color = /^#[\da-f]{6}$/i.test(calendar.color || '') ? calendar.color : undefined;

  return (
    <div className={`calendar-source${calendar.selected === false ? ' is-hidden' : ''}`}>
      <label className="calendar-source-selection" title={name}>
        <input type="checkbox" disabled={busy} checked={calendar.selected !== false}
          aria-label={`${t('Show calendar')}: ${name}`}
          onChange={(event) => void onUpdate(calendar, { selected: event.target.checked })} />
        <span className="calendar-source-color" style={{ backgroundColor: color }} aria-hidden="true" />
        <span className="calendar-source-name">{name}</span>
      </label>
      <div className="calendar-source-meta">
        {calendar.primary && <span>{t('Primary calendar')}</span>}
        {readOnly && <span>{t('Read only')}</span>}
        {sync.tone !== 'success' && <SyncSummary status={calendar.sync_status} enabled={calendar.sync_enabled !== false} />}
      </div>
      <details className="calendar-source-options">
        <summary aria-label={`${t('Calendar settings')}: ${name}`}>
          <Settings2 aria-hidden="true" /><span>{t('Options')}</span><ChevronRight aria-hidden="true" />
        </summary>
        <div className="calendar-source-settings">
          <label title={t('Download events from this calendar.')}>
            <input type="checkbox" disabled={busy} checked={calendar.sync_enabled !== false}
              onChange={(event) => void onUpdate(calendar, { syncEnabled: event.target.checked })} />
            {t('Sync events')}
          </label>
          <label title={t('Events from this calendar count as busy when finding free time.')}>
            <input type="checkbox" disabled={busy} checked={calendar.availability_enabled !== false}
              onChange={(event) => void onUpdate(calendar, { availabilityEnabled: event.target.checked })} />
            {t('Include in availability')}
          </label>
          <SyncDetails status={calendar.sync_status} />
        </div>
      </details>
    </div>
  );
}
