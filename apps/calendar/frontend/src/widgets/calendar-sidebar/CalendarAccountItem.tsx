import { useId, useState } from 'react';
import { AccountAvatar } from '@maverick/account-avatar';
import { CalendarDays, ChevronRight, CircleUserRound, RefreshCw } from 'lucide-react';
import type { CalendarConnection, CalendarRemoteCalendar } from '../../components/ui/calendar-types';
import { t } from '../../preferences';
import type { CalendarOptions } from './CalendarSidebar';
import type { AccountGroup } from './accounts';
import { CalendarSourceItem } from './CalendarSourceItem';
import { SyncSummary } from './sync-status';

export function CalendarAccountItem({ account, busy, filtered, syncing, onSync, onUpdate }: {
  account: AccountGroup;
  busy: boolean;
  filtered: boolean;
  syncing: boolean;
  onSync: (connection: CalendarConnection) => Promise<void>;
  onUpdate: (calendar: CalendarRemoteCalendar, options: CalendarOptions) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(true);
  const calendarsId = useId();
  const isLocal = account.provider === 'local';
  const name = isLocal ? t('Local calendar') : account.name;
  const copy = <span className="calendar-account-copy"><span title={name}>{name}</span>
    <small>{isLocal ? `${account.eventCount} ${t('events')}` : account.displayName || t('Google Calendar')}</small></span>;

  return (
    <section className={`calendar-account${filtered ? ' is-filtered' : ''}`} aria-label={name}>
      <div className="calendar-account-header">
        {isLocal ? <div className="calendar-account-toggle is-local"><CalendarDays aria-hidden="true" />{copy}</div> : (
          <button className="calendar-account-toggle" type="button" aria-expanded={expanded} aria-controls={calendarsId}
            onClick={() => setExpanded(!expanded)}>
            <ChevronRight className={`calendar-account-chevron${expanded ? ' is-expanded' : ''}`} aria-hidden="true" />
            <AccountAvatar pictureUrl={account.connection?.picture_url} fallback={<CircleUserRound />} />{copy}
          </button>
        )}
        {account.connection && <button className="calendar-account-sync" type="button" disabled={busy}
          title={t('Sync now')} aria-label={`${t('Sync now')}: ${name}`}
          onClick={() => void onSync(account.connection!)}>
          <RefreshCw className={syncing ? 'is-spinning' : ''} aria-hidden="true" />
        </button>}
      </div>
      {account.connection && <div className="calendar-account-freshness">
        <SyncSummary status={account.connection.sync_status} last={account.connection.last_sync_at}
          active={syncing} connectionStatus={account.status} showTime />
      </div>}
      {!isLocal && <div className="calendar-account-sources" id={calendarsId} hidden={!expanded}>
        {account.calendars.length ? account.calendars.map((calendar) => (
          <CalendarSourceItem calendar={calendar} busy={busy} key={calendar.id} onUpdate={onUpdate} />
        )) : <p className="calendar-sidebar-empty">{t('Sync this account to load calendars.')}</p>}
      </div>}
    </section>
  );
}
