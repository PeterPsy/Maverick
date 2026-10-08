import { useCalendarPreferences } from "../../useCalendarPreferences";
import { t } from "../../preferences";
import { useEffect, useMemo, useState } from 'react';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { createRoot } from 'react-dom/client';
import { CircleUserRound, RefreshCw, Square, SquareCheck, TriangleAlert } from 'lucide-react';
import { selectCalendar, syncCalendar } from '../../api';
import { useCalendarSidebarReads } from './useCalendarSidebarReads';
import {
  CALENDAR_UI_STATE_RESOURCE,
  readCalendarUiState,
  type CalendarUiState,
} from '../../calendar-ui-state';
import type { CalendarConnection, CalendarRemoteCalendar } from '../../components/ui/calendar-types';
import { buildAccountGroups, type AccountGroup } from './accounts';
import {
  TreeExpander,
  TreeIcon,
  TreeLabel,
  TreeNode,
  TreeNodeContent,
  TreeNodeTrigger,
  TreeProvider,
  TreeView,
} from '../../components/ui/tree';
import { runtimeAppIdFromPathname } from '../../runtime';
import './styles.css';

type CalendarTreeNode = {
  account?: AccountGroup;
  calendar?: CalendarRemoteCalendar;
  children: CalendarTreeNode[];
  id: string;
  label: string;
  loading?: boolean;
  status?: string;
  title: string;
  type: 'account' | 'calendar';
};

function CalendarSidebarWidget() {
  useCalendarPreferences();
  const appId = runtimeAppIdFromPathname(window.location.pathname);
  const { events, localEventCount, connections, calendars, setCalendars, isLoading, error, setError,
    refreshCalendarState, scheduleRefresh } = useCalendarSidebarReads(appId);
  const [uiState, setUiState] = useState<CalendarUiState>(() => readCalendarUiState(appId));
  const [activeOperation, setActiveOperation] = useState('');

  const accountGroups = useMemo(
    () => buildAccountGroups(events, connections, calendars, localEventCount),
    [events, connections, calendars, localEventCount],
  );
  const accountTreeNodes = useMemo(
    () => buildCalendarTree(accountGroups, activeOperation),
    [accountGroups, activeOperation],
  );
  const defaultExpandedIds = useMemo(
    () => accountTreeNodes.flatMap((node) => collectDefaultExpandedIds(node)),
    [accountTreeNodes],
  );
  const selectedNodeIds = useMemo(
    () => uiState.selectedAccounts.length > 0
      ? uiState.selectedAccounts.map((accountId) => calendarAccountIdentity(accountId))
      : [],
    [uiState.selectedAccounts],
  );
  const treeProviderKey = `${accountGroups.length}:${calendars.length}:${defaultExpandedIds.join('|')}`;

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (!isExactMaverickParentMessage(event) || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; resource?: string; type?: string };
      if (payload.owner_app_id !== appId && payload.type !== 'maverick.widget.context-changed') {
        return;
      }
      if (payload.type === 'maverick.widget.context-changed') {
        setUiState(readCalendarUiState(appId));
        scheduleRefresh();
        return;
      }
      if (payload.type === 'maverick.widget.data-changed') {
        if (payload.resource === CALENDAR_UI_STATE_RESOURCE) {
          setUiState(readCalendarUiState(appId));
          return;
        }
        scheduleRefresh();
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId, scheduleRefresh]);

  async function toggleRemoteCalendar(calendar: CalendarRemoteCalendar, checked: boolean) {
    setActiveOperation(calendarIdentity(calendar));
    setError('');
    try {
      const updated = await selectCalendar(appId, calendar.connection_id, calendar.id, {
        selected: checked,
      });
      setCalendars((current) => current.map((item) => (item.connection_id === updated.connection_id && item.provider_calendar_id === updated.provider_calendar_id ? updated : item)));
      notifyCalendarDataChanged(appId, 'calendars');
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : 'Calendar selection failed.');
    } finally {
      setActiveOperation('');
    }
  }

  async function syncConnection(connection: CalendarConnection) {
    if (!connection.id) {
      return;
    }
    setActiveOperation(connection.id);
    setError('');
    try {
      const result = await syncCalendar(appId, connection.id);
      await refreshCalendarState();
      if (!result.synced) setError(t("Sync is partial; continue syncing to fetch remaining pages."));
      notifyCalendarDataChanged(appId, 'events');
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : 'Calendar sync failed.');
    } finally {
      setActiveOperation('');
    }
  }

  function selectTreeNode(node: CalendarTreeNode) {
    if (node.type === 'account') {
      return;
    }
    if (node.type === 'calendar' && node.calendar && activeOperation !== calendarIdentity(node.calendar)) {
      void toggleRemoteCalendar(node.calendar, node.calendar.selected === false);
    }
  }

  return (
    <main className="calendar-sidebar-widget">
      {error ? <p className="calendar-sidebar-empty">{error}</p> : null}

      <div className="calendar-sidebar-list calendar-sidebar-tree-list">
        {isLoading ? (
          <AccountSkeleton />
        ) : (
          <TreeProvider
            animateExpand
            className="calendar-folder-tree"
            defaultExpandedIds={defaultExpandedIds}
            indent={18}
            key={treeProviderKey}
            onSelectionChange={() => undefined}
            selectedIds={selectedNodeIds}
          >
            <TreeView>
              {accountTreeNodes.map((node, index) => (
                <CalendarTreeNodeView
                  activeOperation={activeOperation}
                  isLast={index === accountTreeNodes.length - 1}
                  key={node.id}
                  level={0}
                  node={node}
                  onSelect={selectTreeNode}
                  onSyncConnection={syncConnection}
                />
              ))}
            </TreeView>
          </TreeProvider>
        )}
      </div>
    </main>
  );
}

function CalendarTreeNodeView({ node, level, isLast, onSelect, onSyncConnection, activeOperation }: {
  activeOperation: string;
  isLast: boolean;
  level: number;
  node: CalendarTreeNode;
  onSelect: (node: CalendarTreeNode) => void;
  onSyncConnection: (connection: CalendarConnection) => Promise<void>;
}) {
  const hasChildren = node.children.length > 0 || Boolean(node.type === 'account' && node.account?.provider !== 'local');
  const label = node.status && node.status !== 'connected' ? `${node.label} (${node.status})` : node.label;
  const isCalendarEnabled = node.calendar?.selected !== false;
  const icon = node.type === 'account'
    ? <CircleUserRound className="h-4 w-4" />
    : isCalendarEnabled
      ? <SquareCheck className="calendar-folder-tree-filter-icon is-active h-4 w-4" />
      : <Square className="calendar-folder-tree-filter-icon h-4 w-4" />;

  return (
    <TreeNode isLast={isLast} level={level} nodeId={node.id}>
      <TreeNodeTrigger
        className={node.calendar?.selected === false ? 'calendar-folder-tree-muted' : ''}
        onClick={() => {
          onSelect(node);
        }}
      >
        <TreeExpander hasChildren={hasChildren} />
        <TreeIcon hasChildren={hasChildren} icon={icon} />
        <TreeLabel title={node.title}>{node.loading ? `${label}...` : label}</TreeLabel>
        {node.type === 'account' && node.account?.connection ? (
          <button
            aria-label={`Sync ${node.label}`}
            className="calendar-folder-tree-sync"
            disabled={activeOperation === node.account.id}
            onClick={(event) => {
              event.stopPropagation();
              void onSyncConnection(node.account!.connection!);
            }}
            type="button"
          >
            <RefreshCw className={activeOperation === node.account.id ? 'is-spinning' : ''} aria-hidden="true" />
          </button>
        ) : null}
      </TreeNodeTrigger>
      {node.calendar && <CalendarFlags calendar={node.calendar} onChange={() => notifyCalendarDataChanged(runtimeAppIdFromPathname(window.location.pathname), 'calendars')} />}
      {node.account?.connection && <p className="calendar-sync-status">{syncLabel(node.account.connection.sync_status, node.account.connection.last_sync_at)}</p>}
      <TreeNodeContent hasChildren={hasChildren}>
        {node.children.length === 0 && node.type === 'account' && node.account?.provider !== 'local' ? (
          <TreeNode isLast level={level + 1} nodeId={`${node.id}:empty`}>
            <TreeNodeTrigger className="calendar-folder-tree-status">
              <TreeExpander hasChildren={false} />
              <TreeIcon hasChildren={false} icon={<TriangleAlert className="calendar-folder-tree-alert-icon h-4 w-4" />} />
              <TreeLabel title="Expand to sync this account">Sync this account to load calendars.</TreeLabel>
            </TreeNodeTrigger>
          </TreeNode>
        ) : null}
        {node.children.map((child, index) => (
          <CalendarTreeNodeView
            isLast={index === node.children.length - 1}
            key={child.id}
            level={level + 1}
            node={child}
            activeOperation={activeOperation}
            onSelect={onSelect}
            onSyncConnection={onSyncConnection}
          />
        ))}
      </TreeNodeContent>
    </TreeNode>
  );
}

function syncLabel(status?: { status?: string; error?: string; stale?: boolean; last_sync_at?: string }, last?: string) {
  return `${status?.status || 'idle'} · ${last || status?.last_sync_at ? new Date(last || status!.last_sync_at!).toLocaleString() : t('Never synced')}${status?.stale ? ' · ' + t('Data needs updating') : ''}${status?.error ? ' · ' + status.error : ''}`;
}
function CalendarFlags({ calendar, onChange }: { calendar: CalendarRemoteCalendar; onChange: () => void }) {
  const [error, setError] = useState(''), [saving, setSaving] = useState(false);
  async function toggle(key: 'syncEnabled' | 'availabilityEnabled', value: boolean) {
    setSaving(true); setError('');
    try { await selectCalendar(runtimeAppIdFromPathname(window.location.pathname), calendar.connection_id, calendar.provider_calendar_id, { [key]: value }); onChange() }
    catch (err) { setError(err instanceof Error ? err.message : 'Setting failed') }
    finally { setSaving(false) }
  }
  return <div className="calendar-source-flags"><label><input type="checkbox" disabled={saving} checked={calendar.sync_enabled !== false} onChange={e => void toggle('syncEnabled', e.target.checked)} />{t('Sync')}</label><label><input type="checkbox" disabled={saving} checked={calendar.availability_enabled !== false} onChange={e => void toggle('availabilityEnabled', e.target.checked)} />{t('Availability')}</label><p>{syncLabel(calendar.sync_status)}</p>{calendar.sync_status?.time_min && <p>{new Date(calendar.sync_status.time_min).toLocaleDateString()} – {calendar.sync_status.time_max ? new Date(calendar.sync_status.time_max).toLocaleDateString() : '…'}</p>}{error && <p role="alert">{error}</p>}</div>;
}

function AccountSkeleton() {
  return (
    <div className="calendar-sidebar-skeleton" role="status" aria-label="Calendar accounts are loading">
      {Array.from({ length: 5 }).map((_, index) => (
        <div className={`calendar-sidebar-skeleton__row depth-${Math.min(index, 3)}`} key={index} aria-hidden="true">
          <span className="calendar-sidebar-skeleton__expander" />
          <span className="calendar-sidebar-skeleton__icon" />
          <span className="calendar-sidebar-skeleton__copy">
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

function buildCalendarTree(accounts: AccountGroup[], activeOperation: string): CalendarTreeNode[] {
  return accounts.map((account) => ({
    account,
    children: account.calendars.map((calendar) => ({
      calendar,
      children: [],
      id: calendarIdentity(calendar),
      label: calendar.summary || calendar.provider_calendar_id,
      status: calendar.sync_enabled === false ? 'disabled' : calendar.primary ? 'primary' : calendar.access_role || 'calendar',
      title: calendar.primary ? 'Primary calendar' : calendar.access_role || calendar.provider_calendar_id,
      type: 'calendar',
    })),
    id: calendarAccountIdentity(account.id),
    label: account.name,
    loading: activeOperation === account.id,
    status: account.provider === 'local' ? 'connected' : account.status || 'connected',
    title: `${account.provider === 'local' ? 'Local calendar' : account.status || 'Google Calendar'} • ${account.eventCount} events`,
    type: 'account',
  }));
}

function collectDefaultExpandedIds(node: CalendarTreeNode) {
  const ids: string[] = [];

  function visit(current: CalendarTreeNode) {
    if (current.children.length || current.type === 'account' && current.account?.provider !== 'local') {
      ids.push(current.id);
    }
    current.children.forEach(visit);
  }

  visit(node);
  return ids;
}

function calendarAccountIdentity(accountId: string) {
  return `calendar-account:${accountId}`;
}

function calendarIdentity(calendar: CalendarRemoteCalendar) {
  return `calendar:${calendar.connection_id}:${calendar.id}`;
}

function notifyCalendarDataChanged(appId: string, resource: string) {
  window.parent?.postMessage({ type: 'maverick.app.data-changed', owner_app_id: appId, resource }, "*");
}

createRoot(document.getElementById('calendar-sidebar-root') as HTMLElement).render(<CalendarSidebarWidget />);
