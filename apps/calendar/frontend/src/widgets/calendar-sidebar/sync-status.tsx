import { formatCalendarDate, formatCalendarTime, t } from '../../preferences';

type SyncStatus = {
  status?: string;
  last_sync_at?: string;
  stale?: boolean;
  error?: string;
  has_more?: boolean;
  time_min?: string;
  time_max?: string;
};
type SyncTone = 'success' | 'warning' | 'danger' | 'muted';

function validDate(value?: string) {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

export function syncPresentation(status?: SyncStatus, last?: string, active = false, enabled = true, connectionStatus?: string): {
  label: string;
  tone: SyncTone;
  date?: Date;
} {
  const date = validDate(last) || validDate(status?.last_sync_at);
  if (active) return { label: t('Syncing'), tone: 'muted', date };
  if (connectionStatus === 'error') return { label: t('Account needs attention'), tone: 'danger', date };
  if (connectionStatus === 'disabled') return { label: t('Account disabled'), tone: 'muted', date };
  if (status?.error || status?.status === 'error') return { label: t('Sync failed'), tone: 'danger', date };
  if (!enabled) return { label: t('Sync paused'), tone: 'muted', date };
  if (status?.has_more || status?.status === 'partial') return { label: t('Partial sync'), tone: 'warning', date };
  if (status?.stale && date) return { label: t('Data needs updating'), tone: 'warning', date };
  if (status?.status === 'ok' || status?.status === 'complete') return { label: t('Synced'), tone: 'success', date };
  return { label: t('Never synced'), tone: 'muted', date };
}

export function SyncSummary({ status, last, active, enabled, connectionStatus, showTime = false }: {
  status?: SyncStatus;
  last?: string;
  active?: boolean;
  enabled?: boolean;
  connectionStatus?: string;
  showTime?: boolean;
}) {
  const { label, tone, date } = syncPresentation(status, last, active, enabled, connectionStatus);
  const exact = date ? `${t('Last sync')}: ${formatCalendarDate(date, { dateStyle: 'medium' })}, ${formatCalendarTime(date)}` : '';
  const isToday = date?.toDateString() === new Date().toDateString();
  const compact = date && (isToday ? formatCalendarTime(date) : formatCalendarDate(date, { day: 'numeric', month: 'short' }));
  return (
    <span className={`calendar-sync-summary tone-${tone}`} title={[label, exact, status?.error].filter(Boolean).join(' · ')}>
      <span className="calendar-sync-dot" aria-hidden="true" /><span>{label}</span>
      {showTime && date && !active && <time dateTime={date.toISOString()} aria-label={exact}>{compact}</time>}
    </span>
  );
}

export function SyncDetails({ status }: { status?: SyncStatus }) {
  const last = validDate(status?.last_sync_at);
  const start = validDate(status?.time_min);
  const end = validDate(status?.time_max);
  return <div className="calendar-sync-details">
    <dl>
      <div><dt>{t('Last sync')}</dt><dd>{last ? <time dateTime={last.toISOString()}>
        {formatCalendarDate(last, { dateStyle: 'medium' })}, {formatCalendarTime(last)}
      </time> : t('Never synced')}</dd></div>
      {(start || end) && <div><dt>{t('Downloaded period')}</dt><dd>
        {start ? formatCalendarDate(start, { dateStyle: 'medium' }) : t('No start date')}
        {' – '}{end ? formatCalendarDate(end, { dateStyle: 'medium' }) : t('No end date')}
      </dd></div>}
    </dl>
    {status?.error && <p className="calendar-sidebar-error" role="alert">{status.error}</p>}
  </div>;
}
